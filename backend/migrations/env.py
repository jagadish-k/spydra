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

from spydra.adapters.postgres.tables import PAGE_CURRENT_NAME, SCHEMA, metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)  # alembic.ini's [logger_alembic] audit lines

# The crawl schema's single description (BUILD_PLAN 1.1, ADR-0014). Core
# Table objects, not ORM models — spec 001 §3 makes the entities frozen
# dataclasses and repositories translate rows by hand, so nothing is mapped.
target_metadata = metadata

_VIEWS = {PAGE_CURRENT_NAME.split(".")[-1]}

# The crawl schema is the only thing this chain may touch. `ui` and drizzle's
# ledger belong to the BFF (spec 010 §3, ADR-0021) and `public` to nobody;
# reflecting them would have autogenerate propose DROPs for another service's
# tables.
_OURS = {SCHEMA}


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep autogenerate inside `crawl`, and off the views.

    Two filters, and the schema one is load-bearing. `target_metadata` is a
    `MetaData(schema="crawl")`, so with `include_schemas=False` alembic
    reflects only the *default* schema and sees none of the twelve crawl
    tables — while all twelve sit in the metadata. Autogenerate's conclusion
    is that the whole schema is missing, and `make revision` against a fully
    migrated database emits `create_table` for all twelve plus every index.
    Measured, not reasoned about: it did exactly that, and the resulting
    revision fails on "relation already exists".

    So `include_schemas=True` is required — and the moment it is on, alembic
    also sees `ui` and `drizzle`, which this chain must never manage. Hence
    the schema filter below.

    `page_current` is a view (ADR-0007) with no place in the metadata.
    Reflection returns it looking like a table alembic has never heard of,
    and its next move is to propose dropping it.
    """
    if type_ == "table" and name in _VIEWS:
        return False
    return True


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Confine REFLECTION to `crawl`.

    This has to be `include_name` and not `include_object`: the latter is
    consulted after reflection, and reflecting a schema the api role cannot
    read fails outright — `permission denied for schema drizzle`, which is
    correct, since `ui` and drizzle's ledger belong to the BFF (spec 010 §3,
    ADR-0021) and `spydra_api` is deliberately granted nothing there.
    Filtering by name happens first, so those schemas are never touched.

    Both halves were measured. With `include_schemas=False` autogenerate saw
    no crawl tables at all and proposed creating all twelve. With
    `include_schemas=True` and no name filter it crashed on `drizzle`.
    """
    if type_ == "schema":
        return name in _OURS
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
        include_schemas=True,
        include_name=include_name,
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
        # include_schemas=True is REQUIRED for autogenerate to see anything:
        # target_metadata is MetaData(schema="crawl") and there is no
        # search_path, so with False alembic reflects only the default schema
        # and concludes every crawl table is missing. include_object confines
        # it to `crawl` so `ui` and drizzle's ledger are never managed here.
        include_schemas=True,
        include_name=include_name,
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
