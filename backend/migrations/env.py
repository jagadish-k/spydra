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

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)  # alembic.ini's [logger_alembic] audit lines

# target_metadata stays None until the domain models exist; autogenerate
# (make revision) is wired to them by BUILD_PLAN 1.1.
target_metadata = None

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
