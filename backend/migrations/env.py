"""Alembic environment for the crawl schema (ADR-0014: asyncpg driver, async
engine). The URL always comes from DATABASE_URL; alembic.ini carries none.

The crawl schema itself is created by docker/init-schemas.sql on first boot —
migrations never emit CREATE SCHEMA crawl (the api role would also fail:
it holds CREATE on the schema, not the database).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from spydra.adapters.postgres.tables import PAGE_CURRENT_NAME, metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)  # alembic.ini's [logger_alembic] audit lines

# The crawl schema's single description (BUILD_PLAN 1.1, ADR-0014). Core
# Table objects, not ORM models — spec 001 §3 makes the entities frozen
# dataclasses and repositories translate rows by hand, so nothing is mapped.
target_metadata = metadata

_VIEWS = {PAGE_CURRENT_NAME.split(".")[-1]}


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep autogenerate off the views.

    `page_current` is a view (ADR-0007) and so has no place in the metadata.
    Reflection returns it looking like a table it has never heard of, and
    autogenerate's next move is to propose dropping it — in a revision
    someone would then run. Filtering it is cheaper than discovering that.
    """
    if type_ == "table" and name in _VIEWS:
        return False
    return True


# The alembic ledger lives inside crawl — the same ownership rule as the
# drizzle chain, whose ledger lives in ui (spec 010 §3): each chain's
# bookkeeping stays in the schema it owns, so neither role needs rights
# outside its own schema to migrate.
VERSION_TABLE_SCHEMA = "crawl"


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (`alembic upgrade --sql`)."""
    context.configure(
        url=os.environ["DATABASE_URL"],
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # include_schemas=False: only crawl objects are migrated and they are
        # addressed explicitly; the api role's search_path stays untouched.
        include_schemas=False,
        include_object=include_object,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(os.environ["DATABASE_URL"], poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
