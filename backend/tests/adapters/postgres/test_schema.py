"""The crawl schema, against real Postgres (spec 001 §6, TESTING.md §1).

These assert on the things that are *constraints* rather than column lists: a
partial unique index and a DISTINCT ON view behave the way the system depends
on them behaving, or the guarantees built on top of them are decoration. None
of it is expressible in SQLite, which is why TESTING.md §1 rules SQLite out.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from spydra.adapters.postgres.tables import SCHEMA, metadata

pytestmark = pytest.mark.integration

EXPECTED_TABLES = frozenset(t.name for t in metadata.sorted_tables)


async def test_the_migration_created_every_table_in_the_metadata(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
        ),
        {"s": SCHEMA},
    )
    present = {r[0] for r in rows}
    assert EXPECTED_TABLES <= present, f"missing: {sorted(EXPECTED_TABLES - present)}"


async def test_spec_001_section_1_is_complete(conn: AsyncConnection) -> None:
    """Named explicitly rather than derived from the metadata.

    Deriving it from `tables.py` would make this test agree with whatever
    `tables.py` happens to say; the point is to agree with the spec.
    `template_drafts` and `field_vocabulary` are absent on purpose — spec 001
    §4 puts them in phase 4 and §1 does not contain them.
    """
    expected = {
        "domains",
        "templates",
        "pages",
        "runs",
        "page_observations",
        "crawl_queue",
        "assets",
        "observation_assets",
        "unknown_pages",
        "run_events",
        "asset_queue",
        "template_samples",
    }
    assert expected == EXPECTED_TABLES


async def test_page_current_is_a_view_not_a_table(conn: AsyncConnection) -> None:
    """ADR-0007: current state is a view. A table could be UPDATEd, and
    AGENTS.md rule 13 would then be a convention instead of a shape."""
    kind = await conn.scalar(
        sa.text(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = :s AND table_name = 'page_current'"
        ),
        {"s": SCHEMA},
    )
    assert kind == "VIEW"


@pytest.mark.parametrize("enum_name", ["domain_state", "run_state"])
async def test_enum_types_exist_in_the_crawl_schema(conn: AsyncConnection, enum_name: str) -> None:
    found = await conn.scalar(
        sa.text(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = :s AND t.typname = :t"
        ),
        {"s": SCHEMA, "t": enum_name},
    )
    assert found == enum_name


async def _a_domain(conn: AsyncConnection, host: str) -> int:
    domain_id = await conn.scalar(
        sa.text(f"INSERT INTO {SCHEMA}.domains (host) VALUES (:h) RETURNING id"), {"h": host}
    )
    assert domain_id is not None
    return int(domain_id)


async def _a_run(conn: AsyncConnection, domain_id: int) -> int:
    run_id = await conn.scalar(
        sa.text(
            f"INSERT INTO {SCHEMA}.runs (domain_ids) VALUES (ARRAY[:d]::bigint[]) RETURNING id"
        ),
        {"d": domain_id},
    )
    assert run_id is not None
    return int(run_id)


async def _a_template(conn: AsyncConnection, domain_id: int, *, version: int, active: bool) -> int:
    template_id = await conn.scalar(
        sa.text(
            f"INSERT INTO {SCHEMA}.templates "
            "(domain_id, name, url_pattern, page_kind, version, is_active) "
            "VALUES (:d, 'product', '^/products/', 'product', :v, :a) RETURNING id"
        ),
        {"d": domain_id, "v": version, "a": active},
    )
    assert template_id is not None
    return int(template_id)


async def test_one_active_template_per_pattern(conn: AsyncConnection) -> None:
    """Spec 001 §6 and ADR-0006: the partial unique index guarantees exactly
    one live template per pattern while every prior version stays readable."""
    domain_id = await _a_domain(conn, "one-active.test")
    await _a_template(conn, domain_id, version=1, active=True)

    with pytest.raises(IntegrityError):
        await _a_template(conn, domain_id, version=2, active=True)


async def test_prior_versions_stay_readable(conn: AsyncConnection) -> None:
    """The other half of the same index: it is partial *so that* history is
    kept. A plain unique constraint would force deleting the old version."""
    domain_id = await _a_domain(conn, "versions.test")
    await _a_template(conn, domain_id, version=1, active=False)
    await _a_template(conn, domain_id, version=2, active=False)
    await _a_template(conn, domain_id, version=3, active=True)

    count = await conn.scalar(
        sa.text(f"SELECT count(*) FROM {SCHEMA}.templates WHERE domain_id = :d"),
        {"d": domain_id},
    )
    assert count == 3


async def test_page_current_returns_exactly_the_newest_observation(
    conn: AsyncConnection,
) -> None:
    """Spec 001 §6. Three observations of one page, inserted out of order so
    the view's ORDER BY is actually exercised rather than agreeing with
    insertion order by accident."""
    domain_id = await _a_domain(conn, "current.test")
    run_id = await _a_run(conn, domain_id)
    page_id = await conn.scalar(
        sa.text(
            f"INSERT INTO {SCHEMA}.pages (domain_id, url, url_hash) "
            "VALUES (:d, 'https://current.test/products/1', sha256('u')) RETURNING id"
        ),
        {"d": domain_id},
    )
    for price, when in (
        ("10.0000", "2026-10-02 00:00:00+00"),
        ("30.0000", "2026-10-03 00:00:00+00"),  # newest, inserted in the middle
        ("20.0000", "2026-10-01 00:00:00+00"),
    ):
        await conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.page_observations "
                "(page_id, run_id, observed_at, http_status, price_amount) "
                "VALUES (:p, :r, :t, 200, :a)"
            ),
            {"p": page_id, "r": run_id, "t": when, "a": price},
        )

    rows = (
        await conn.execute(
            sa.text(f"SELECT page_id, price_amount FROM {SCHEMA}.page_current WHERE page_id = :p"),
            {"p": page_id},
        )
    ).all()

    assert len(rows) == 1
    assert rows[0].price_amount == pytest.approx(30.0)


async def test_observations_dedupe_nothing_and_keep_every_row(conn: AsyncConnection) -> None:
    """ADR-0007: append-only. There is deliberately no unique constraint that
    would stop a second observation of the same page in the same run — the
    history is the point, and `content_hash` is how repeat crawls stay cheap
    rather than how they are rejected."""
    domain_id = await _a_domain(conn, "append.test")
    run_id = await _a_run(conn, domain_id)
    page_id = await conn.scalar(
        sa.text(
            f"INSERT INTO {SCHEMA}.pages (domain_id, url, url_hash) "
            "VALUES (:d, 'https://append.test/p/1', sha256('v')) RETURNING id"
        ),
        {"d": domain_id},
    )
    for _ in range(3):
        await conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.page_observations (page_id, run_id, http_status) "
                "VALUES (:p, :r, 200)"
            ),
            {"p": page_id, "r": run_id},
        )
    count = await conn.scalar(
        sa.text(f"SELECT count(*) FROM {SCHEMA}.page_observations WHERE page_id = :p"),
        {"p": page_id},
    )
    assert count == 3


async def test_crawl_queue_dedupes_within_a_run(conn: AsyncConnection) -> None:
    """Spec 001 §1: UNIQUE (run_id, url_hash). The same URL may be queued
    again in a *later* run — that is a re-crawl, not a duplicate."""
    domain_id = await _a_domain(conn, "queue.test")
    run_ids = [await _a_run(conn, domain_id) for _ in range(2)]

    def insert(run_id: int) -> sa.TextClause:
        return sa.text(
            f"INSERT INTO {SCHEMA}.crawl_queue (run_id, domain_id, url, url_hash) "
            f"VALUES ({run_id}, {domain_id}, 'https://queue.test/a', sha256('a'))"
        )

    await conn.execute(insert(run_ids[0]))
    await conn.execute(insert(run_ids[1]))  # different run: allowed

    with pytest.raises(IntegrityError):
        await conn.execute(insert(run_ids[0]))  # same run: rejected
