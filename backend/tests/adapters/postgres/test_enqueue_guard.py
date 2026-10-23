"""`Frontier.enqueue` adds work only where someone will do it (2.3 review,
finding 1).

A row added to a halted domain, or to a run that has finished, is never
claimed. The first strands the run in `running` for ever; the second adds
work to a run whose report is already written. So the enqueue inserts only
while the domain is `active` and the run `running`, **decided in the same
statement as the insert**, under a share lock on the domain row. A check
made before the insert is a race with a worker halting the domain in
between, and that race is tested here with two real connections, as 1.8's
frontier tests are: one connection cannot race itself.

Committed rows (`clean_crawl`): the frontier opens its own transactions.
"""

import asyncio
import time

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.domain.ids import DomainId, RunId
from tests.adapters.postgres.seed import seed_domain, seed_queue_row, seed_run
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_canonical_pages import build, make_due
from tests.scheduler.test_link_discovery import seed_halden

pytestmark = pytest.mark.integration

HOST = "halden.test"
BASE = f"https://{HOST}"


async def queue(engine: AsyncEngine, run: RunId) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text("SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r"),
                {"r": int(run)},
            )
        ).all()
    return {r.url: r.state for r in rows}


async def set_state(engine: AsyncEngine, table: str, row_id: int, state: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(f"UPDATE crawl.{table} SET state = :s WHERE id = :i"),  # noqa: S608  # table is a literal from this file
            {"s": state, "i": row_id},
        )


async def live(engine: AsyncEngine) -> tuple[DomainId, RunId]:
    domain = await seed_domain(engine, HOST)
    return domain, await seed_run(engine, [int(domain)])


LINKS = [(f"{BASE}/shop/p/HT-CD-001", 1), (f"{BASE}/shop/p/HT-CD-002", 1)]


async def test_an_active_domain_in_a_running_run_is_enqueued(clean_crawl: AsyncEngine) -> None:
    """The control: without it, every refusal below would pass against an
    enqueue that had stopped inserting anything."""
    domain, run = await live(clean_crawl)

    assert (await PostgresFrontier(clean_crawl).enqueue(run, domain, LINKS, cap=20_000)).added == 2
    assert await queue(clean_crawl, run) == {u: "pending" for u, _ in LINKS}


@pytest.mark.parametrize("state", ["paused", "broken", "awaiting_approval"])
async def test_a_domain_that_is_not_active_gets_nothing(
    clean_crawl: AsyncEngine, state: str
) -> None:
    domain, run = await live(clean_crawl)
    await set_state(clean_crawl, "domains", int(domain), state)

    assert (await PostgresFrontier(clean_crawl).enqueue(run, domain, LINKS, cap=20_000)).added == 0
    assert await queue(clean_crawl, run) == {}


@pytest.mark.parametrize("state", ["completed", "stopped", "paused"])
async def test_a_run_that_is_not_running_gets_nothing(clean_crawl: AsyncEngine, state: str) -> None:
    domain, run = await live(clean_crawl)
    await set_state(clean_crawl, "runs", int(run), state)

    assert (await PostgresFrontier(clean_crawl).enqueue(run, domain, LINKS, cap=20_000)).added == 0
    assert await queue(clean_crawl, run) == {}


async def test_duplicates_in_one_call_are_one_row_and_the_count_is_of_new_rows(
    clean_crawl: AsyncEngine,
) -> None:
    """Three spellings of one page, a second page, and a page already in the
    run: two new rows, and the return value says two."""
    domain, run = await live(clean_crawl)
    already = f"{BASE}/shop/cutting/discs"
    await seed_queue_row(clean_crawl, run, domain, already)
    urls = [
        (f"{BASE}/shop/p/HT-CD-001", 1),
        (f"{BASE}/shop/p/HT-CD-001#top", 1),
        (f"{BASE}/shop/p/HT-CD-001?utm_source=x", 1),
        (f"{BASE}/shop/p/HT-CD-002", 1),
        (f"{already}/", 1),
    ]

    assert (await PostgresFrontier(clean_crawl).enqueue(run, domain, urls, cap=20_000)).added == 2
    assert set(await queue(clean_crawl, run)) == {
        already,
        f"{BASE}/shop/p/HT-CD-001",
        f"{BASE}/shop/p/HT-CD-002",
    }


async def _waiting_on_a_lock(engine: AsyncEngine, timeout: float = 5.0) -> bool:
    """Is some other backend blocked on a lock? Polled from pg_stat_activity
    rather than inferred from elapsed time, so the test does not depend on
    how fast the machine is."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with engine.connect() as conn:
            waiting = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                    )
                )
            ).scalar_one()
        if waiting:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_an_enqueue_racing_a_halt_waits_for_it_and_inserts_nothing(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """Worker A halts the domain and abandons its rows, in one transaction
    not yet committed. Worker B's discovery enqueues meanwhile. B must wait
    for A, then see the domain halted and insert nothing. Not waiting, it
    reads the last committed state (`active`), inserts, and A's abandon has
    already run: rows nobody will claim, and a run that never drains."""
    domain, run = await live(clean_crawl)
    halter = create_async_engine(database_url)
    enqueuer = create_async_engine(database_url)
    try:
        async with halter.connect() as a:
            trans = await a.begin()
            await a.execute(
                sa.text("UPDATE crawl.domains SET state = 'broken' WHERE id = :d"),
                {"d": int(domain)},
            )
            await a.execute(
                sa.text(
                    "UPDATE crawl.crawl_queue SET state = 'abandoned' "
                    "WHERE run_id = :r AND domain_id = :d AND state = 'pending'"
                ),
                {"r": int(run), "d": int(domain)},
            )

            pending = asyncio.create_task(
                PostgresFrontier(enqueuer).enqueue(run, domain, LINKS, cap=20_000)
            )
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await halter.dispose()
        await enqueuer.dispose()

    assert waited and not done_early, "the enqueue did not wait for the halt"
    assert (outcome.added, outcome.capped) == (0, False)
    assert await queue(clean_crawl, run) == {}


async def test_a_page_crawled_after_its_domain_was_halted_elsewhere_lets_the_run_finish(
    clean_crawl: AsyncEngine,
) -> None:
    """The reviewer's reproduction. This worker claimed the seed; another
    halted the domain and abandoned its rows while the seed was in flight.
    This page's own write saw no halt, so only the enqueue's guard stops its
    links. Without it, they are `pending` on a `broken` domain and the run
    never drains."""
    engine = clean_crawl
    with FixtureSite() as site:
        domain, run, _ = await seed_halden(engine, site.base_url)
        await make_due(engine, domain)
        frontier = PostgresFrontier(engine)
        item = await frontier.claim()
        assert item is not None
        await set_state(engine, "domains", int(domain), "broken")
        await frontier.abandon_domain(run, domain)
        static = HttpxFetcher(SystemClock())
        try:
            await build(engine, static).crawl(item)
        finally:
            await static.aclose()

    assert list((await queue(engine, run)).values()) == ["done"], "links were enqueued"
    await PostgresRuns(engine).finish_drained()
    async with engine.connect() as conn:
        state = (
            await conn.execute(
                sa.text("SELECT state::text FROM crawl.runs WHERE id = :r"), {"r": int(run)}
            )
        ).scalar_one()
    assert state == "completed"
