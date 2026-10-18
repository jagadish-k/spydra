"""Shared fixtures.

Integration tests run against **real Postgres** on a **separate database**
(TESTING.md §1). Both halves of that are enforced here rather than trusted:

- `SKIP LOCKED`, `DISTINCT ON`, partial unique indexes and JSONB operators
  either do not exist in SQLite or behave differently, so a SQLite suite
  would be testing a different system — and the concurrency guarantee is the
  thing most worth testing.
- A suite pointed at the dev database destroys the data you were looking at,
  and `downgrade base` in a migration test would take the whole schema with
  it. `_require_test_database` refuses to run rather than letting that be a
  thing someone discovers once.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run at all if pytest-asyncio is not active.

    Without it, every async fixture here is unhandled and the integration
    tests fail as ten `requested an async fixture ... with no plugin or hook
    that handled it` / `pytest_fixture_post_finalizer` errors, with the only
    real clue — `PytestConfigWarning: Unknown config option: asyncio_mode` —
    printed in the warnings summary at the very bottom.

    That has now happened twice. The usual cause is not a missing line in
    `pyproject.toml` but a **stale `venv` named volume**: compose seeds
    `venv:/app/.venv` from the image the first time the volume is created and
    never re-seeds it, so a rebuilt image with a new dependency does not
    reach a volume that already exists. `make up --build` is not enough;
    `make reset-deps` is what drops it.

    One legible failure beats ten misleading ones.
    """
    if not config.pluginmanager.hasplugin("asyncio"):
        raise pytest.UsageError(
            "pytest-asyncio is not active, so every async fixture in this suite "
            "is unrunnable.\n"
            "  - Installed but disabled? Drop any `-p no:asyncio`.\n"
            "  - Not installed? The venv volume is almost certainly stale — the\n"
            "    image seeds it only on first creation:\n"
            "        make reset-deps && make up && make test-api\n"
            "  - Not in the lock? `grep pytest-asyncio backend/uv.lock`, then\n"
            "    `make lock` if it is missing."
        )


# The guard. A database whose name does not end here is not a test database,
# whatever the variable it arrived in was called.
_TEST_DB_SUFFIX = "_test"


def _require_test_database() -> str:
    """The URL integration tests may touch, or a hard failure.

    `make test-api` overrides DATABASE_URL with TEST_DATABASE_URL, so either
    name resolving to a `*_test` database is fine; anything else is not.
    """
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail(
            "No TEST_DATABASE_URL or DATABASE_URL. Integration tests need real "
            "Postgres (TESTING.md §1) — run them with `make test-api`."
        )
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not name.endswith(_TEST_DB_SUFFIX):
        pytest.fail(
            f"Refusing to run integration tests against database {name!r}: it does "
            f"not end in {_TEST_DB_SUFFIX!r}. The suite migrates and truncates what "
            "it is pointed at, and one of its tests runs `downgrade base`. Use "
            "`make test-api`, which points at spydra_test."
        )
    return url


@pytest.fixture(scope="session")
def database_url() -> str:
    return _require_test_database()


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    """An Alembic config aimed at the test database.

    `migrations/env.py` reads DATABASE_URL from the environment and nothing
    else (alembic.ini deliberately carries no URL), so the environment is
    where this has to be set.
    """
    os.environ["DATABASE_URL"] = database_url
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


@pytest.fixture(scope="session")
def migrated(alembic_config: Config, database_url: str) -> None:
    """Bring the test database to head, once per session.

    **Not autouse.** The unit tests must not need a database — making this
    autouse would mean a developer with no stack running sees the lifecycle
    and transform tests fail for want of Postgres, which teaches them to stop
    trusting the suite. Only `engine` depends on it, so only the tests that
    reach for a connection pay for one.

    The suite owns its own schema state rather than expecting someone to
    remember `make migrate` against spydra_test first: that failure runs in
    the direction where a new migration is silently not under test.
    """
    command.upgrade(alembic_config, "head")


@pytest.fixture
async def engine(database_url: str, migrated: None) -> AsyncIterator[AsyncEngine]:
    """Function-scoped on purpose.

    A session-scoped async fixture has to pin pytest-asyncio's loop scope to
    match, and getting that wrong fails as a closed event loop several tests
    later. An engine is cheap — the pool is lazy — so the simpler lifetime
    wins. Lane A's two-worker tests create their own engines anyway, because
    the point there is two genuinely separate connections.
    """
    eng = create_async_engine(database_url)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection in a transaction that is rolled back afterwards.

    TESTING.md §1: every test gets one of these **except the concurrency
    tests**, which need real committed rows and clean up after themselves.
    Two workers cannot see each other's uncommitted work, so a rolled-back
    transaction would let a `SKIP LOCKED` test pass without ever exercising
    the lock — which is the one thing that suite exists to exercise. Those
    tests take `engine` and manage their own transactions.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
