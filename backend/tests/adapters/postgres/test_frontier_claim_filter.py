"""The claim takes only a domain with work, for the pool that asks
(BUILD_PLAN 1.13, ADR-0034, spec 002 §1 and §6).

Real Postgres, committed rows, the real `PostgresFrontier`: the claim's
eligibility is one SQL statement and the only honest way to test it is to
run it.

**Each test makes the wrong domain the MOST eligible one** (the earlier
`next_eligible_at`). The claim orders by that column, so a query that
lacked the predicate under test would pick the wrong domain first, and the
test goes red rather than passing on a lucky ordering.
"""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.domain.enums import RenderMode
from spydra.domain.ids import DomainId
from spydra.scheduler.pools import RENDERED_MODES, STATIC_MODES
from tests.adapters.postgres.seed import domain_row, seed_domain, seed_queue_row, seed_run

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
LONG_AGO = NOW - timedelta(hours=1)
RECENTLY = NOW - timedelta(minutes=1)


async def _set_render_mode(engine: AsyncEngine, domain_id: DomainId, mode: RenderMode) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.domains SET render_mode = :m WHERE id = :id"),
            {"m": mode.value, "id": int(domain_id)},
        )


async def test_a_drained_domain_does_not_starve_one_with_pending_work(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0034. The drained domain is active, due, and the most eligible
    by `next_eligible_at`, and it has nothing to fetch: one `done` row from
    earlier in the run. The claim must go past it to the domain with work."""
    drained = await seed_domain(clean_crawl, "drained.test", next_eligible_at=LONG_AGO)
    busy = await seed_domain(clean_crawl, "busy.test", next_eligible_at=RECENTLY)
    run = await seed_run(clean_crawl, [int(drained), int(busy)])
    await seed_queue_row(clean_crawl, run, drained, "https://drained.test/a", state="done")
    wanted = await seed_queue_row(clean_crawl, run, busy, "https://busy.test/p")

    frontier = PostgresFrontier(clean_crawl)
    item = await frontier.claim()

    assert item is not None, "a domain with an empty queue starved the one with work"
    assert item.id == wanted
    assert item.domain_id == busy
    # The drained domain's gate was not taken on the way past.
    assert (await domain_row(clean_crawl, drained)).in_flight == 0


async def test_a_drained_domain_keeps_not_starving_across_repeated_claims(
    clean_crawl: AsyncEngine,
) -> None:
    """The starvation was permanent, not occasional: the drained domain is
    never fetched, so it stays the most eligible for good. Every pending row
    of the other domain must come out, claim after claim."""
    drained = await seed_domain(clean_crawl, "drained.test", next_eligible_at=LONG_AGO)
    busy = await seed_domain(clean_crawl, "busy.test", next_eligible_at=RECENTLY)
    run = await seed_run(clean_crawl, [int(drained), int(busy)])
    rows = {
        await seed_queue_row(clean_crawl, run, busy, f"https://busy.test/p{n}") for n in range(3)
    }

    frontier = PostgresFrontier(clean_crawl)
    claimed = set()
    for _ in range(3):
        async with clean_crawl.begin() as conn:
            # Hand the gate back as a completion would; the delay is not
            # what this test is about.
            await conn.execute(
                sa.text(
                    "UPDATE crawl.domains SET in_flight = 0, next_eligible_at = :due WHERE id = :id"
                ),
                {"due": RECENTLY, "id": int(busy)},
            )
        item = await frontier.claim()
        assert item is not None
        claimed.add(int(item.id))

    assert claimed == rows
    assert await frontier.claim() is None


async def test_the_rendered_pool_never_claims_a_static_domains_row(
    clean_crawl: AsyncEngine,
) -> None:
    static = await seed_domain(clean_crawl, "static.test", next_eligible_at=LONG_AGO)
    rendered = await seed_domain(clean_crawl, "rendered.test", next_eligible_at=RECENTLY)
    await _set_render_mode(clean_crawl, rendered, RenderMode.RENDERED)
    run = await seed_run(clean_crawl, [int(static), int(rendered)])
    await seed_queue_row(clean_crawl, run, static, "https://static.test/p")
    wanted = await seed_queue_row(clean_crawl, run, rendered, "https://rendered.test/p")

    frontier = PostgresFrontier(clean_crawl)
    item = await frontier.claim(frozenset({RenderMode.RENDERED}))

    assert item is not None and item.id == wanted
    # With the rendered domain's only row taken, the static row is still
    # not the rendered pool's to take.
    assert await frontier.claim(RENDERED_MODES) is None
    assert (await domain_row(clean_crawl, static)).in_flight == 0


async def test_the_static_pool_never_claims_a_rendered_domains_row(
    clean_crawl: AsyncEngine,
) -> None:
    rendered = await seed_domain(clean_crawl, "rendered.test", next_eligible_at=LONG_AGO)
    await _set_render_mode(clean_crawl, rendered, RenderMode.RENDERED)
    static = await seed_domain(clean_crawl, "static.test", next_eligible_at=RECENTLY)
    run = await seed_run(clean_crawl, [int(static), int(rendered)])
    await seed_queue_row(clean_crawl, run, rendered, "https://rendered.test/p")
    wanted = await seed_queue_row(clean_crawl, run, static, "https://static.test/p")

    frontier = PostgresFrontier(clean_crawl)
    item = await frontier.claim(STATIC_MODES)

    assert item is not None and item.id == wanted
    assert await frontier.claim(STATIC_MODES) is None
    assert (await domain_row(clean_crawl, rendered)).in_flight == 0


async def test_the_static_pool_claims_auto_domains(clean_crawl: AsyncEngine) -> None:
    """An AUTO domain fetches static first (spec 012 §4), so it belongs to
    the static pool, and the rendered pool must leave it alone."""
    auto = await seed_domain(clean_crawl, "auto.test")
    await _set_render_mode(clean_crawl, auto, RenderMode.AUTO)
    run = await seed_run(clean_crawl, [int(auto)])
    wanted = await seed_queue_row(clean_crawl, run, auto, "https://auto.test/p")

    frontier = PostgresFrontier(clean_crawl)
    assert await frontier.claim(RENDERED_MODES) is None
    item = await frontier.claim(STATIC_MODES)
    assert item is not None and item.id == wanted
