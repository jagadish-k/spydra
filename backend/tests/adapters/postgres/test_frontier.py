"""`PostgresFrontier`, single worker, against real Postgres (BUILD_PLAN 1.8).

The two-worker guarantee lives in `test_frontier_concurrency.py` — separate
file because those tests must commit and must not share a transaction, and
mixing the two shapes is how a `SKIP LOCKED` test ends up inside a
transaction nobody else can see.

Written from spec 002 §1–3 and the `Frontier` port's docstrings, not from the
adapter. Where a test looks like it is asserting something trivial, the
reason is usually in the port: `release()`'s docstring, for instance, spells
out that returning a row without decrementing `in_flight` leaves the domain
unclaimable until the sweep — a stall caused by our own sidecar being busy.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import LEASE_SECONDS, MAX_ATTEMPTS, PostgresFrontier
from spydra.ports.frontier import Completion, Frontier, QueueItemState
from tests.adapters.postgres.seed import (
    domain_row,
    queue_row,
    seed_domain,
    seed_queue_row,
    seed_run,
)

pytestmark = pytest.mark.integration


def frontier(engine: AsyncEngine) -> PostgresFrontier:
    return PostgresFrontier(engine)


# ---------------------------------------------------------------------------
# E1 — what a claim does, all of it
# ---------------------------------------------------------------------------


async def test_a_claim_leases_the_row_and_takes_the_gate(clean_crawl: AsyncEngine) -> None:
    """One transaction does five things, and a test that checked only the
    returned row would miss three of them. `in_flight` is the one that
    matters most: since ADR-0026 it IS the gate, so a claim that leased the
    row without incrementing it would let the next worker straight through."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    before = datetime.now(UTC)
    claimed = await frontier(engine).claim()
    assert claimed is not None

    assert int(claimed.id) == item_id
    assert claimed.url == "https://v.test/a"
    assert claimed.attempts == 1, "the attempt is charged by the claim, not by completion"

    row = await queue_row(engine, item_id)
    assert row.state == QueueItemState.IN_FLIGHT
    assert row.attempts == 1
    assert row.locked_until is not None
    # The lease is a real future deadline, not a null that the sweep would
    # then treat as never expiring.
    assert row.locked_until > before
    assert row.locked_until <= before + timedelta(seconds=LEASE_SECONDS + 5)

    assert (await domain_row(engine, domain)).in_flight == 1, "the gate was not taken"


# ---------------------------------------------------------------------------
# E2 — None is the ordinary case, and each reason gets its own test
# ---------------------------------------------------------------------------


async def test_an_empty_queue_claims_nothing(clean_crawl: AsyncEngine) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    await seed_run(engine, [int(domain)])
    assert await frontier(engine).claim() is None


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        pytest.param("not active", {"state": "paused"}, id="paused-domain"),
        pytest.param("not active", {"state": "broken"}, id="broken-domain"),
        pytest.param(
            "not yet due",
            {"next_eligible_at": datetime.now(UTC) + timedelta(minutes=5)},
            id="not-yet-eligible",
        ),
        pytest.param(
            "gate already held",
            {"max_concurrency": 1, "in_flight": 1},
            id="in-flight-at-capacity",
        ),
    ],
)
async def test_each_reason_a_domain_is_ineligible_is_tested_separately(
    clean_crawl: AsyncEngine, label: str, kwargs: dict[str, object]
) -> None:
    """One "returns None" test would pass against a query broken for a
    different reason than the one being exercised — and three of these four
    reasons are separate clauses in the `eligible` CTE."""
    engine = clean_crawl
    domain = await seed_domain(engine, **kwargs)  # type: ignore[arg-type]
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")

    assert await frontier(engine).claim() is None, label


async def test_a_second_slot_is_available_when_max_concurrency_allows_it(
    clean_crawl: AsyncEngine,
) -> None:
    """The gate is `in_flight < max_concurrency`, not `in_flight = 0`. A
    query that hard-coded one concurrent fetch per domain would pass every
    test above and quietly ignore the operator's setting."""
    engine = clean_crawl
    domain = await seed_domain(engine, max_concurrency=2)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await seed_queue_row(engine, run, domain, "https://v.test/b")

    f = frontier(engine)
    assert await f.claim() is not None
    assert await f.claim() is not None
    assert await f.claim() is None, "the third claim exceeded max_concurrency"
    assert (await domain_row(engine, domain)).in_flight == 2


# ---------------------------------------------------------------------------
# E3 — breadth-first
# ---------------------------------------------------------------------------


async def test_depth_orders_before_id_so_listings_drain_first(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 002 §1: listing pages fan out into product URLs, so draining them
    early keeps the frontier full and stops workers starving at the end of a
    run. The deeper row is inserted FIRST, so an `ORDER BY id` would take it
    and the assertion would fail — ordering by insertion order is the
    plausible mistake here."""
    engine = clean_crawl
    domain = await seed_domain(engine, max_concurrency=3)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/deep", depth=3)
    await seed_queue_row(engine, run, domain, "https://v.test/shallow", depth=0)
    await seed_queue_row(engine, run, domain, "https://v.test/middle", depth=1)

    f = frontier(engine)
    urls = [(await f.claim()), (await f.claim()), (await f.claim())]
    assert [c.url for c in urls if c is not None] == [
        "https://v.test/shallow",
        "https://v.test/middle",
        "https://v.test/deep",
    ]


# ---------------------------------------------------------------------------
# E8, E9 — completion and release
# ---------------------------------------------------------------------------


async def test_completion_writes_the_politeness_state_it_was_handed(
    clean_crawl: AsyncEngine,
) -> None:
    """The frontier persists; it does not compute. `Completion`'s three domain
    fields are already-computed values from the gate (`1.9`), and a frontier
    that recomputed any of them would be a second component with an opinion
    about politeness."""
    engine = clean_crawl
    domain = await seed_domain(engine, crawl_delay_ms=2000)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = frontier(engine)
    claimed = await f.claim()
    assert claimed is not None

    due = datetime.now(UTC) + timedelta(seconds=4)
    await f.complete(
        claimed,
        Completion(
            state=QueueItemState.DONE,
            next_eligible_at=due,
            crawl_delay_ms=4000,
            consecutive_failures=2,
        ),
    )

    row = await queue_row(engine, item_id)
    assert row.state == QueueItemState.DONE
    # A closed row with a live lease is a row the sweep would later touch.
    assert row.locked_until is None

    dom = await domain_row(engine, domain)
    assert dom.crawl_delay_ms == 4000
    assert dom.consecutive_failures == 2
    assert dom.next_eligible_at == due
    assert dom.in_flight == 0, "completion must give the gate back"


async def test_completion_persists_the_consecutive_403_count(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0004's pause is only real if this count survives the queue row.

    Added in `1.9` after review found the gate computing `consecutive_403s`
    with nowhere to put it: no column, and no field on `Completion`. The
    count was discarded the moment `complete()` ran, so a domain that 403s
    twice and is then picked up by a restarted worker — or by another replica
    — came back with zero and refused for ever without ever reaching three.
    That is the outcome ADR-0004 exists to prevent, and it passed every unit
    test in the gate's own suite.

    In-process politeness state is also what ADR-0003 and ADR-0026 rejected,
    for this reason.
    """
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = frontier(engine)
    claimed = await f.claim()
    assert claimed is not None

    await f.complete(
        claimed,
        Completion(
            state=QueueItemState.FAILED,
            next_eligible_at=datetime.now(UTC),
            crawl_delay_ms=2000,
            consecutive_failures=2,
            consecutive_403s=2,
        ),
    )

    row = await domain_row(engine, domain)
    assert row.consecutive_403s == 2, (
        "the refusal count was not persisted, so ADR-0004's pause cannot survive a worker restart"
    )
    # ...and it is distinct from the shared counter, which is the whole point.
    assert row.consecutive_failures == 2


async def test_the_403_count_defaults_to_zero_and_can_be_cleared(
    clean_crawl: AsyncEngine,
) -> None:
    """A success resets it, and the reset has to reach the database too —
    otherwise a domain that recovers stays two refusals from a pause for
    ever."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    assert (await domain_row(engine, domain)).consecutive_403s == 0

    f = frontier(engine)
    claimed = await f.claim()
    assert claimed is not None
    await f.complete(
        claimed,
        Completion(
            state=QueueItemState.DONE,
            next_eligible_at=datetime.now(UTC),
            crawl_delay_ms=2000,
            consecutive_failures=0,
            consecutive_403s=0,
        ),
    )
    assert (await domain_row(engine, domain)).consecutive_403s == 0


async def test_release_gives_the_gate_back_and_charges_nothing(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 002 §6 and the port's docstring. "No penalty" means no
    `consecutive_failures`, no backoff **and no attempt charged** — but it
    does not mean holding the gate. Releasing without decrementing
    `in_flight` leaves the domain unclaimable until the sweep, which is a
    stall caused by our own sidecar being busy: exactly what "try another
    domain" exists to avoid."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = frontier(engine)
    claimed = await f.claim()
    assert claimed is not None
    await f.release(claimed)

    row = await queue_row(engine, item_id)
    assert row.state == QueueItemState.PENDING
    assert row.locked_until is None
    assert row.attempts == 0, "backpressure is not an attempt to charge the domain"

    assert (await domain_row(engine, domain)).in_flight == 0
    # ...and the proof that the gate is really back: it can be claimed again.
    assert await f.claim() is not None


# ---------------------------------------------------------------------------
# E6, E7 — the sweep, which ADR-0026 made load-bearing
# ---------------------------------------------------------------------------


async def test_an_expired_lease_returns_the_row_and_reconciles_the_counter(
    clean_crawl: AsyncEngine,
) -> None:
    """Both halves, because with ADR-0026 the first one alone is not enough.
    An `in_flight` left high by a dead worker stops that domain being claimed
    **at all**, so a sweep that returned the row without reconciling the
    counter would fix the visible symptom and leave the stall in place."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(
        engine,
        run,
        domain,
        "https://v.test/a",
        state="in_flight",
        attempts=1,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    f = frontier(engine)
    assert await f.claim() is None, "the domain should be gated before the sweep"

    assert await f.sweep_expired_leases() == 1

    assert (await queue_row(engine, item_id)).state == QueueItemState.PENDING
    assert (await domain_row(engine, domain)).in_flight == 0
    assert await f.claim() is not None, "the domain is still stalled after the sweep"


async def test_a_live_lease_is_left_alone(clean_crawl: AsyncEngine) -> None:
    """A sweep that recovered rows whose lease has not expired would steal
    work from a worker that is still fetching — and the supplier would see
    two requests for one page."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(
        engine,
        run,
        domain,
        "https://v.test/a",
        state="in_flight",
        locked_until=datetime.now(UTC) + timedelta(seconds=60),
    )

    assert await frontier(engine).sweep_expired_leases() == 0
    assert (await queue_row(engine, item_id)).state == QueueItemState.IN_FLIGHT


async def test_the_third_attempt_fails_the_row_rather_than_retrying_again(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 002 §3. A row that keeps coming back to `pending` is a row the
    crawler retries forever against a page that will not load."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(
        engine,
        run,
        domain,
        "https://v.test/a",
        state="in_flight",
        attempts=MAX_ATTEMPTS,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert await frontier(engine).sweep_expired_leases() == 1
    assert (await queue_row(engine, item_id)).state == QueueItemState.FAILED


async def test_the_sweep_corrects_a_counter_with_no_expired_rows_at_all(
    clean_crawl: AsyncEngine,
) -> None:
    """The reconcile is a recount, not a decrement of what the sweep
    recovered. A domain whose counter drifted high with nothing in flight —
    a worker killed between the claim commit and its own crash handling — is
    stalled forever if the reconcile only ever subtracts rows it saw."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=3)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = frontier(engine)
    assert await f.claim() is None

    await f.sweep_expired_leases()

    assert (await domain_row(engine, domain)).in_flight == 0
    assert await f.claim() is not None


# ---------------------------------------------------------------------------
# E12 — the one drift direction ADR-0026 calls impolite
# ---------------------------------------------------------------------------


async def test_in_flight_never_goes_negative(clean_crawl: AsyncEngine) -> None:
    """ADR-0026 §Consequences. Completion and the sweep both decrement, so a
    completion racing a sweep of the same row can double-decrement — and once
    the counter is negative, `in_flight < max_concurrency` passes more often
    than it should and two workers fetch one host concurrently. Actual
    rudeness, arrived at through the gate.

    The `CHECK (in_flight >= 0)` on the table is the loud backstop; this
    asserts the adapter does not need it, by completing and releasing more
    times than the counter was ever incremented."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = frontier(engine)
    claimed = await f.claim()
    assert claimed is not None

    completion = Completion(
        state=QueueItemState.DONE,
        next_eligible_at=datetime.now(UTC),
        crawl_delay_ms=2000,
        consecutive_failures=0,
    )
    await f.complete(claimed, completion)
    await f.complete(claimed, completion)  # the double-decrement
    await f.release(claimed)  # and again, from the other direction

    assert (await domain_row(engine, domain)).in_flight == 0
    assert item_id == int(claimed.id)


# ---------------------------------------------------------------------------
# E10, E11 — abandon and enqueue
# ---------------------------------------------------------------------------


async def test_abandon_records_the_work_and_leaves_other_domains_alone(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0004: the rows a paused domain never got to stay in the queue
    marked `abandoned`, so the run report shows the work that was not done
    rather than reporting a clean finish. An `abandon` that deleted them, or
    that reached across domains, would lose exactly that."""
    engine = clean_crawl
    paused = await seed_domain(engine, host="northfield.test")
    other = await seed_domain(engine, host="orbis.test")
    run = await seed_run(engine, [int(paused), int(other)])

    a = await seed_queue_row(engine, run, paused, "https://n.test/a")
    b = await seed_queue_row(engine, run, paused, "https://n.test/b")
    done = await seed_queue_row(engine, run, paused, "https://n.test/c", state="done")
    untouched = await seed_queue_row(engine, run, other, "https://o.test/a")

    assert await frontier(engine).abandon_domain(run, paused) == 2

    assert (await queue_row(engine, a)).state == QueueItemState.ABANDONED
    assert (await queue_row(engine, b)).state == QueueItemState.ABANDONED
    finished = await queue_row(engine, done)
    assert finished.state == QueueItemState.DONE, "a finished row is not abandoned"
    assert (await queue_row(engine, untouched)).state == QueueItemState.PENDING


async def test_enqueue_deduplicates_within_a_run_but_not_across_runs(
    clean_crawl: AsyncEngine,
) -> None:
    """`UNIQUE (run_id, url_hash)` (spec 001 §1). Within a run a link found
    twice is one row; the next run must be able to crawl the same URL again,
    or a second run would enqueue nothing."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    first = await seed_run(engine, [int(domain)])
    second = await seed_run(engine, [int(domain)])

    f = frontier(engine)
    both = [("https://v.test/a", 0), ("https://v.test/b", 1)]
    again = [("https://v.test/a", 0)]
    assert (await f.enqueue(first, domain, both, cap=20_000)).added == 2
    assert (await f.enqueue(first, domain, again, cap=20_000)).added == 0, (
        "a duplicate within the run"
    )
    assert (await f.enqueue(second, domain, again, cap=20_000)).added == 1, (
        "a new run means new work"
    )
    assert (await f.enqueue(first, domain, [], cap=20_000)).added == 0


async def test_enqueued_rows_are_claimable_with_their_depth(
    clean_crawl: AsyncEngine,
) -> None:
    """Enqueue and claim have to agree about `depth`, or breadth-first
    ordering silently stops working on rows the crawler discovered itself —
    which is every row after the seeds."""
    engine = clean_crawl
    domain = await seed_domain(engine, max_concurrency=2)
    run = await seed_run(engine, [int(domain)])

    f = frontier(engine)
    await f.enqueue(
        run, domain, [("https://v.test/deep", 2), ("https://v.test/top", 0)], cap=20_000
    )

    first = await f.claim()
    second = await f.claim()
    assert first is not None and second is not None
    assert (first.url, first.depth) == ("https://v.test/top", 0)
    assert (second.url, second.depth) == ("https://v.test/deep", 2)


def test_the_adapter_satisfies_the_frontier_protocol(engine: AsyncEngine) -> None:
    """`mypy --strict` through the annotation, as in 1.6 and 1.7 — no port is
    `@runtime_checkable`, and adding that to satisfy a test would be the test
    changing the port."""
    adapter: Frontier = PostgresFrontier(engine)
    assert adapter is not None


async def test_the_claim_sql_still_locks_the_domain_row(clean_crawl: AsyncEngine) -> None:
    """A guard on the SQL text itself, which is unusual and earns its place.

    ADR-0026 says in terms that "a reviewer who does not understand why there
    are two row locks will simplify it back into the bug", and the bug is
    SILENT — Postgres accepts the simplified query and locks only
    `crawl_queue`. The two-worker test in the sibling file is the real proof,
    but it is slow and someone under pressure may be tempted to narrow it.
    This one is instant and names the ADR in its failure message.
    """
    from spydra.adapters.postgres.frontier import _CLAIM

    sql = str(_CLAIM)
    assert sql.count("FOR UPDATE SKIP LOCKED") == 2, (
        "the claim must hold TWO row locks: one on crawl.domains (the politeness "
        "gate, serialising the eligibility decision) and one on crawl.crawl_queue "
        "(the dequeue). Read ADR-0026 before changing this — with only the second, "
        "two workers fetched one host concurrently in 20 rounds out of 20."
    )
    domains_cte = sql.split("claimed AS")[0]
    assert "FOR UPDATE SKIP LOCKED" in domains_cte, (
        "the lock on crawl.domains is gone, which is the exact defect ADR-0026 was written about"
    )
    assert "in_flight = d.in_flight + 1" in sql, (
        "the claim must take the gate in the same statement (ADR-0026 defect 2)"
    )
    assert isinstance(clean_crawl, AsyncEngine)


async def test_no_statement_in_this_adapter_decides_politeness(
    clean_crawl: AsyncEngine,
) -> None:
    """The division of labour from the port's docstring, asserted on the SQL.

    The frontier persists; the gate (`1.9`) computes. If jitter, a doubling
    or a decay ever appears in here, two components have opinions about when
    a domain may be fetched and they will disagree.
    """
    import spydra.adapters.postgres.frontier as mod

    text = "".join(
        str(getattr(mod, name)) for name in dir(mod) if name.startswith("_") and name.isupper()
    )
    for arithmetic in ("random(", "* 2", "0.9", "1.3", "0.7"):
        assert arithmetic not in text, (
            f"{arithmetic!r} looks like politeness arithmetic, which belongs to the "
            "gate in 1.9, not to the frontier (ports/frontier.py)"
        )
    assert isinstance(clean_crawl, AsyncEngine)
