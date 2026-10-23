"""The per-domain URL cap and its run-scoped halt, at the adapter (BUILD_PLAN
2.5, ADR-0040).

The cap's enforcement is a count guard inside the guarded enqueue: while
the count of this run's rows for the domain is below the cap the whole
batch inserts — it may overshoot; at or past it nothing does, and the
statement says so (`capped`). The overshoot is deliberately bounded, not
exact (ADR-0040, against ADR-0026): what is asserted here is the invariant
the ADR states — never beyond the cap plus one batch per concurrent
enqueuer — never an exactness it disclaims.

The halt is one transaction: abandon the pending rows for this
`(run, domain)`, then fail the run under a `state = 'running'` fence —
first-signaller-wins — with the reason verbatim and `pages_abandoned`
counted by the same `_STATS` shape as every finish. The domain row is
never touched.
"""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spydra.adapters.postgres.domains import PostgresDomains
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.domain.ids import DomainId, RunId
from tests.adapters.postgres.seed import seed_domain, seed_queue_row, seed_run

pytestmark = pytest.mark.integration

HOST = "halden.test"
BASE = f"https://{HOST}"
REASON = "url cap exceeded: 5 urls queued for halden.test"


def links(n: int, start: int = 0) -> list[tuple[str, int]]:
    return [(f"{BASE}/shop/p/HT-CD-{i:03d}", 1) for i in range(start, start + n)]


async def queue_count(engine: AsyncEngine, run: int, domain: int) -> int:
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM crawl.crawl_queue"
                        " WHERE run_id = :r AND domain_id = :d"
                    ),
                    {"r": run, "d": domain},
                )
            ).scalar_one()
        )


# ---------------------------------------------------------------------------
# The column (spec 004 §3: default 20,000; operator-editable, positive)
# ---------------------------------------------------------------------------


async def test_a_new_domain_defaults_to_a_cap_of_20000(clean_crawl: AsyncEngine) -> None:
    """The default is calibrated to the fixture's reachable facet space
    being just above it (2.1): crossed by a trap, not by an honest crawl.
    Read back as the crawl path reads it, through the repository."""
    domain = await seed_domain(clean_crawl, HOST)

    async with clean_crawl.connect() as conn:
        column = (
            await conn.execute(
                sa.text("SELECT url_cap FROM crawl.domains WHERE id = :d"), {"d": int(domain)}
            )
        ).scalar_one()
    entity = await PostgresDomains(clean_crawl).get(domain)

    assert column == 20000
    assert entity.url_cap == 20000


async def test_the_cap_must_be_positive(clean_crawl: AsyncEngine) -> None:
    """A cap of zero would fail every enqueue and halt every run on its
    first discovery; the migration's CHECK refuses it."""
    domain = await seed_domain(clean_crawl, HOST)

    with pytest.raises(IntegrityError):
        async with clean_crawl.begin() as conn:
            await conn.execute(
                sa.text("UPDATE crawl.domains SET url_cap = 0 WHERE id = :d"), {"d": int(domain)}
            )


# ---------------------------------------------------------------------------
# The count guard inside the guarded enqueue
# ---------------------------------------------------------------------------


async def test_the_enqueue_signals_the_cap_the_moment_the_count_reaches_it(
    clean_crawl: AsyncEngine,
) -> None:
    """Five links under a cap of five: all five insert (the count was
    below), and the statement signals `capped` — the count after the batch
    has reached the cap. Everything after that refuses: nothing inserts,
    and every call still says `capped`, because rows within a run are
    never deleted."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    frontier = PostgresFrontier(clean_crawl)

    crossing = await frontier.enqueue(run, domain, links(5), cap=5)
    assert (crossing.added, crossing.capped) == (5, True)
    for more in (links(3, start=5), links(2, start=8)):
        refused = await frontier.enqueue(run, domain, more, cap=5)
        assert (refused.added, refused.capped) == (0, True)

    assert await queue_count(clean_crawl, int(run), int(domain)) == 5


async def test_a_batch_is_all_or_nothing_and_may_overshoot(
    clean_crawl: AsyncEngine,
) -> None:
    """While the count is below the cap the WHOLE batch inserts — there
    are no partial batches — which is exactly how a trap's batch overshoots
    the cap. The overshoot is the signal: the count after the batch is at
    or past the cap."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])

    outcome = await PostgresFrontier(clean_crawl).enqueue(run, domain, links(8), cap=5)

    assert (outcome.added, outcome.capped) == (8, True)
    assert await queue_count(clean_crawl, int(run), int(domain)) == 8


async def test_every_state_counts_toward_the_cap(clean_crawl: AsyncEngine) -> None:
    """The cap counts rows, not pending work: a done row and an abandoned
    row were still work discovery produced, and under ADR-0040 they are
    what makes the count a durable breach flag."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    await seed_queue_row(clean_crawl, run, domain, f"{BASE}/shop/cutting/discs", state="done")
    await seed_queue_row(clean_crawl, run, domain, f"{BASE}/shop/cutting/blades", state="abandoned")

    outcome = await PostgresFrontier(clean_crawl).enqueue(run, domain, links(1), cap=2)

    assert (outcome.added, outcome.capped) == (0, True)
    assert await queue_count(clean_crawl, int(run), int(domain)) == 2


async def test_two_concurrent_enqueuers_overshoot_by_at_most_one_batch_each(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """ADR-0040's stated race, with two real connections: both enqueuers
    can see a count below the cap and both insert. The invariant is the
    one the ADR dares to state — the total never exceeds the cap plus one
    batch per concurrent enqueuer — and once the count is at the cap,
    every further enqueue refuses and signals."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    a, b = create_async_engine(database_url), create_async_engine(database_url)
    cap, batch = 5, 3
    try:
        outcomes = await asyncio.gather(
            PostgresFrontier(a).enqueue(run, domain, links(batch), cap=cap),
            PostgresFrontier(b).enqueue(run, domain, links(batch, start=10), cap=cap),
        )
        total = await queue_count(clean_crawl, int(run), int(domain))

        assert cap <= total <= cap + 2 * batch, (
            f"the overshoot broke the ADR-0040 bound: {total} rows for a cap of {cap}"
        )
        assert all(o.added in (0, batch) for o in outcomes), outcomes

        after = PostgresFrontier(clean_crawl)
        for _ in range(2):
            refused = await after.enqueue(run, domain, links(2, start=20), cap=cap)
            assert (refused.added, refused.capped) == (0, True)
        assert await queue_count(clean_crawl, int(run), int(domain)) == total
    finally:
        await a.dispose()
        await b.dispose()


# ---------------------------------------------------------------------------
# The halt (ADR-0040): run-scoped, first-signaller-wins
# ---------------------------------------------------------------------------


async def seed_breach_shape(engine: AsyncEngine) -> tuple[int, int, int]:
    """A run over two active domains: the first with three pending rows
    plus one done and one failed, the second with two pending rows — the
    shape that distinguishes 'pending only', 'this domain only' and 'the
    domain row is untouched'."""
    first = await seed_domain(engine, HOST)
    second = await seed_domain(engine, "elsewhere.test")
    run = await seed_run(engine, [int(first), int(second)])
    for i in range(3):
        await seed_queue_row(engine, run, first, f"{BASE}/shop/p/HT-CD-00{i + 1}")
    await seed_queue_row(engine, run, first, f"{BASE}/shop/cutting/discs", state="done")
    await seed_queue_row(engine, run, first, f"{BASE}/shop/cutting/blades", state="failed")
    for i in range(2):
        await seed_queue_row(engine, run, second, f"https://elsewhere.test/x/{i}")
    return int(run), int(first), int(second)


async def the_run(engine: AsyncEngine, run: int) -> sa.Row[object]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT state::text AS s, stop_reason, finished_at, stats"
                    " FROM crawl.runs WHERE id = :r"
                ),
                {"r": run},
            )
        ).one()


async def queue_states(engine: AsyncEngine, run: int, domain: int) -> dict[str, list[str]]:
    async with engine.connect() as conn:
        rows_ = (
            await conn.execute(
                sa.text(
                    "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r AND domain_id = :d"
                ),
                {"r": run, "d": domain},
            )
        ).all()
    out: dict[str, list[str]] = {}
    for url, state in rows_:
        out.setdefault(state, []).append(url)
    return out


async def test_the_halt_fails_the_run_abandons_only_this_domains_pending_and_leaves_the_domain(
    clean_crawl: AsyncEngine,
) -> None:
    run, first, second = await seed_breach_shape(clean_crawl)

    halt = await PostgresFrontier(clean_crawl).halt_run(RunId(run), DomainId(first), REASON)

    assert (halt.abandoned, halt.transitioned) == (3, True)

    row = await the_run(clean_crawl, run)
    assert row.s == "failed"
    assert row.stop_reason == REASON
    assert row.finished_at is not None
    assert row.stats["pages_abandoned"] == 3, "the failure was written without the abandon"

    # Pending only: the done and failed rows record work that did and did
    # not happen; the halt must not rewrite them.
    states = await queue_states(clean_crawl, run, first)
    assert sorted(states) == ["abandoned", "done", "failed"]
    assert len(states["abandoned"]) == 3

    # This domain only: the second domain's pending rows are another
    # domain's work in the same run.
    assert set(await queue_states(clean_crawl, run, second)) == {"pending"}

    # The domain row is untouched — run-scoped by design.
    for domain in (first, second):
        async with clean_crawl.connect() as conn:
            state = (
                await conn.execute(
                    sa.text("SELECT state::text FROM crawl.domains WHERE id = :d"), {"d": domain}
                )
            ).scalar_one()
        assert state == "active"


async def test_only_the_first_signaller_transitions_and_the_recording_stands(
    clean_crawl: AsyncEngine,
) -> None:
    """A re-signal — an in-flight page finding the cap already breached —
    abandons nothing (nothing is pending) and transitions nothing, so the
    first signaller's recording is what stands: same state, same reason,
    same stats."""
    run, first, _ = await seed_breach_shape(clean_crawl)
    frontier = PostgresFrontier(clean_crawl)
    await frontier.halt_run(RunId(run), DomainId(first), REASON)
    before = await the_run(clean_crawl, run)

    again = await frontier.halt_run(RunId(run), DomainId(first), REASON)

    assert (again.abandoned, again.transitioned) == (0, False)
    after = await the_run(clean_crawl, run)
    assert (after.s, after.stop_reason, after.stats) == (before.s, before.stop_reason, before.stats)


async def test_a_run_that_already_finished_cleanly_is_not_failed_under_the_halt(
    clean_crawl: AsyncEngine,
) -> None:
    """The other half of the fence: a halt arriving after the sweep closed
    the run must not fail a finished run, and says it transitioned
    nothing."""
    run, first, _ = await seed_breach_shape(clean_crawl)
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.runs SET state = 'completed', finished_at = now() WHERE id = :r"),
            {"r": run},
        )

    halt = await PostgresFrontier(clean_crawl).halt_run(RunId(run), DomainId(first), REASON)

    assert halt.transitioned is False
    row = await the_run(clean_crawl, run)
    assert row.s == "completed"
    assert row.stop_reason is None


async def test_a_failed_run_is_never_drained_into_a_clean_finish(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0040's atomicity point: after the breach, the queue has nothing
    left to claim, so a sweep that ran now would love to write
    `completed` — and must refuse, because the run is no longer `running`.
    Either outcome alone (abandoned rows, or a failed state) is weak;
    both together are the 'not a clean finish' the ADR demands."""
    run, first, _ = await seed_breach_shape(clean_crawl)
    await PostgresFrontier(clean_crawl).halt_run(RunId(run), DomainId(first), REASON)

    finished = await PostgresRuns(clean_crawl).finish_drained()

    assert finished == []
    row = await the_run(clean_crawl, run)
    assert row.s == "failed"
    assert row.stats["pages_abandoned"] == 3
