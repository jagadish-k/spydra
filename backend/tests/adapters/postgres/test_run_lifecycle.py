"""The run lifecycle at the adapter: transitions, fences, the CHECK
(BUILD_PLAN 2.7, ADR-0041, spec 001 §2's run transition table).

**Claimable ⇔ the run is `running`.** That one predicate, and its two
writer siblings (the sweep's and the release's terminal CASE branches),
are what make stop terminal and pause resumable. Every test here is
against real Postgres with committed rows, because each mechanism under
test is one SQL statement and the only honest way to test a predicate is
to run it against a row that satisfies the other side.

The transition table's every valid edge is pinned here or in the sibling
files named below; the invalid transitions are pinned as fenced misses —
the guarded UPDATE matches nothing and the caller is told the run's
actual state, which is the whole of "an operator CLI must never print a
lie". The real-worker acceptance (stop mid-crawl, pause/resume through
the subprocess) lives in `tests/scheduler/test_run_control.py`.

- `running → completed` (drained finish) and the completion races: here.
- `running → failed` (cap halt): `test_url_cap.py` at adapter level, and
  `test_trap_crawls.py` through the worker; the edge is pinned here once
  too, so the table is complete in one file.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spydra.adapters.postgres.frontier import (
    _ENQUEUE,
    _LOCK_RUN_FOR_RELEASE,
    _RELEASE_DOMAIN,
    _RELEASE_QUEUE,
    MAX_ATTEMPTS,
    PostgresFrontier,
    url_hash,
)
from spydra.adapters.postgres.runs import (
    _ABANDON_RUN,
    _FINISH_IF_DRAINED,
    _LOCK_RUN_FOR_STOP,
    _STOP_RUN,
    STOP_REASON_OPERATOR,
    PostgresRuns,
)
from spydra.domain.ids import DomainId, RunId
from spydra.ports.frontier import ClaimedUrl, QueueItemState
from tests.adapters.postgres.seed import queue_row, seed_domain, seed_queue_row, seed_run
from tests.adapters.postgres.test_enqueue_guard import _waiting_on_a_lock

pytestmark = pytest.mark.integration

# States the CHECK allows with a NULL stop_reason. `paused` is on this list
# deliberately (ADR-0041): it is resumable, not terminal.
NULL_REASON_OK = ("running", "paused", "completed")
# The enum's terminal set; only `completed` may end without a reason.
TERMINAL = ("completed", "stopped", "failed")


async def mark_run(
    engine: AsyncEngine, run: RunId, state: str, *, reason: str | None = None
) -> None:
    """Park a run in `state` the way a real transition would.

    Terminal states other than `completed` write a reason because the CHECK
    demands one — a fixture that parked `stopped` bare would fail on the
    constraint, not on the behaviour under test.
    """
    if reason is None and state in TERMINAL and state != "completed":
        reason = "fixture"
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.runs SET state = CAST(:s AS crawl.run_state), "
                "stop_reason = :r, finished_at = CASE WHEN :s = 'running'"
                " THEN NULL ELSE now() END WHERE id = :i"
            ),
            {"s": state, "r": reason, "i": int(run)},
        )


async def run_row(engine: AsyncEngine, run: RunId) -> sa.Row[Any]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT state::text AS state, stop_reason, finished_at, stats"
                    " FROM crawl.runs WHERE id = :i"
                ),
                {"i": int(run)},
            )
        ).one()


# ---------------------------------------------------------------------------
# 1. The claim fence — claimable ⇔ run is running
# ---------------------------------------------------------------------------


async def test_a_running_runs_pending_row_is_claimed(clean_crawl: AsyncEngine) -> None:
    """The control. Without it every refusal below would pass against a
    claim that had stopped claiming anything at all."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")

    assert await PostgresFrontier(engine).claim() is not None


async def test_a_pending_row_of_a_non_running_run_is_never_claimed(
    clean_crawl: AsyncEngine,
) -> None:
    """The whole pause/stop mechanism in one predicate. The domain is
    active, due, at zero in-flight, and the row is `pending` — everything
    ADR-0034 calls work — but the run is not `running`, so the row is not
    claimable. For a terminal run this is the row that reached `pending`
    after the stop (ADR-0041 names it: the fence must be exact); for
    `paused` it is pause itself.
    """
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await mark_run(engine, run, "paused")

    assert await PostgresFrontier(engine).claim() is None


@pytest.mark.parametrize("state", TERMINAL, ids=TERMINAL)
async def test_a_terminal_runs_pending_row_is_never_claimed(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """`stopped` and `failed` are what a released-then-marked row can sit
    under; `completed` is a finished run a late discovery targeted. None of
    their rows is claimable, ever again — the run cannot be resurrected."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await mark_run(engine, run, state)

    assert await PostgresFrontier(engine).claim() is None


async def test_the_fence_is_per_run_not_per_domain(clean_crawl: AsyncEngine) -> None:
    """A stopped run must not poison its domain: the next run's rows on the
    same domain stay claimable. Stop's run-scoped abandon has already taken
    the stopped run's own rows out of `pending`, so the domain's only work
    is the new run's — and the claim must take it."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    stopped = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, stopped, domain, "https://v.test/old")
    outcome = await PostgresRuns(engine).stop_run(stopped)
    assert outcome.transitioned and outcome.abandoned == 1

    fresh = await seed_run(engine, [int(domain)])
    wanted = await seed_queue_row(engine, fresh, domain, "https://v.test/new")

    item = await PostgresFrontier(engine).claim()
    assert item is not None, "a stopped run fenced its whole domain"
    assert (item.id, item.run_id) == (wanted, fresh)


# ---------------------------------------------------------------------------
# 2. The sweep's routing — a terminal run's row does not go back to pending
# ---------------------------------------------------------------------------


async def _expired_row(
    engine: AsyncEngine, run: RunId, domain: DomainId, url: str, *, attempts: int = 1
) -> int:
    return await seed_queue_row(
        engine,
        run,
        domain,
        url,
        state="in_flight",
        attempts=attempts,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )


@pytest.mark.parametrize("state", TERMINAL, ids=TERMINAL)
async def test_an_expired_lease_on_a_terminal_run_is_abandoned_not_pending(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """A dead worker's row returns via the sweep, not via the release, so
    the sweep carries the same rule. Routed to `pending` it would be
    unclaimable for ever (the claim fence holds) but unreported — the
    silent hole in the work-not-done number stop exists to report."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await _expired_row(engine, run, domain, "https://v.test/a")
    await mark_run(engine, run, state)

    assert await PostgresFrontier(engine).sweep_expired_leases() == 1
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED


async def test_an_expired_lease_on_a_paused_run_returns_to_pending(
    clean_crawl: AsyncEngine,
) -> None:
    """Pause keeps every row. A swept in-flight row of a paused run is
    still the operator's queued work, waiting for resume — abandoning it
    would make resume crawl a subset of what was paused, silently."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await _expired_row(engine, run, domain, "https://v.test/a")
    await mark_run(engine, run, "paused")

    assert await PostgresFrontier(engine).sweep_expired_leases() == 1
    assert (await queue_row(engine, item_id)).state == QueueItemState.PENDING


async def test_an_exhausted_row_fails_even_on_a_stopped_run(clean_crawl: AsyncEngine) -> None:
    """The CASE's ordering, pinned: `attempts >= max` wins over run state.
    A poisoned row on a stopped run is `failed`, not `abandoned` — an
    exhausted row failed against the site, and that is the accurate record
    whatever the run did afterwards."""
    engine = clean_crawl
    domain = await seed_domain(engine, in_flight=1)
    run = await seed_run(engine, [int(domain)])
    item_id = await _expired_row(engine, run, domain, "https://v.test/a", attempts=MAX_ATTEMPTS)
    await mark_run(engine, run, "stopped")

    assert await PostgresFrontier(engine).sweep_expired_leases() == 1
    assert (await queue_row(engine, item_id)).state == QueueItemState.FAILED


# ---------------------------------------------------------------------------
# 3. The release's routing — SIGTERM and backpressure after a stop
# ---------------------------------------------------------------------------


async def test_a_row_released_after_stop_lands_abandoned(clean_crawl: AsyncEngine) -> None:
    """The no-resurrection path an operator actually drives: the worker is
    SIGTERM'd (or backpressured) mid-fetch on a run the operator already
    stopped. Released to `pending` it would sit on a terminal run
    unclaimable and unreported; the fence and this CASE together make the
    terminal state hold no pending rows at the write."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = PostgresFrontier(engine)
    item = await f.claim()
    assert item is not None and int(item.id) == item_id
    outcome = await PostgresRuns(engine).stop_run(run)
    assert outcome.transitioned, "the run was not running when stopped"

    assert await f.release(item) is True
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED


async def test_a_row_released_under_pause_returns_to_pending(clean_crawl: AsyncEngine) -> None:
    """Pause's release is the ordinary one: the row is queued work, not
    work not done."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await seed_queue_row(engine, run, domain, "https://v.test/a")

    f = PostgresFrontier(engine)
    item = await f.claim()
    assert item is not None
    assert (await PostgresRuns(engine).pause_run(run)).transitioned

    assert await f.release(item) is True
    assert (await queue_row(engine, item_id)).state == QueueItemState.PENDING


# ---------------------------------------------------------------------------
# 4. The enqueue fence — pause freezes dequeue, not discovery
# ---------------------------------------------------------------------------


async def test_a_paused_runs_in_flight_tail_still_discovers(clean_crawl: AsyncEngine) -> None:
    """The positive case 2.3's guard refused and ADR-0041 widened: a paused
    run's discovery still enqueues. A paused run's in-flight tail crawls
    and discovers; dropping those links would make resume a silently
    incomplete crawl — the worst failure mode a pause can have, and it
    leaves no trace. (Terminal runs getting nothing is pinned in
    `test_enqueue_guard.py`.)"""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await mark_run(engine, run, "paused")

    outcome = await PostgresFrontier(engine).enqueue(
        run, domain, [("https://v.test/found", 1)], cap=20_000
    )

    assert outcome.added == 1, "a paused run's discovery was dropped"
    row = await run_row(engine, run)
    assert row.state == "paused"


# ---------------------------------------------------------------------------
# 5. The transitions — every valid edge, and the misses
# ---------------------------------------------------------------------------


async def test_pause_moves_running_to_paused_and_touches_nothing_else(
    clean_crawl: AsyncEngine,
) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await seed_queue_row(engine, run, domain, "https://v.test/b", state="done")

    outcome = await PostgresRuns(engine).pause_run(run)

    assert outcome.transitioned is True
    row = await run_row(engine, run)
    assert row.state == "paused"
    assert row.stop_reason is None, "paused is not terminal and names no reason"
    assert row.finished_at is None
    states = [(await queue_row(engine, i)).state for i in await _ids_of_run(engine, run)]
    assert states == [QueueItemState.PENDING, QueueItemState.DONE], "pause touched a row"


async def _ids_of_run(engine: AsyncEngine, run: RunId) -> list[int]:
    async with engine.connect() as conn:
        return [
            int(r.id)
            for r in await conn.execute(
                sa.text("SELECT id FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id"),
                {"r": int(run)},
            )
        ]


@pytest.mark.parametrize("state", ("paused", *TERMINAL), ids=("paused", *TERMINAL))
async def test_pause_on_anything_but_running_misses_and_reports_the_state(
    clean_crawl: AsyncEngine, state: str
) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await mark_run(engine, run, state)

    outcome = await PostgresRuns(engine).pause_run(run)

    assert outcome.transitioned is False
    assert outcome.state == state
    assert (await run_row(engine, run)).state == state


async def test_resume_returns_a_paused_run_to_running_and_claims_flow_again(
    clean_crawl: AsyncEngine,
) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    runs = PostgresRuns(engine)
    assert (await runs.pause_run(run)).transitioned
    assert await PostgresFrontier(engine).claim() is None, "the fence held while paused"

    outcome = await runs.resume_run(run)

    assert outcome.transitioned is True
    assert outcome.stats is None, "work remained; resume must not complete the run"
    assert (await run_row(engine, run)).state == "running"
    assert await PostgresFrontier(engine).claim() is not None, "claims did not resume"


async def test_resume_completes_a_run_that_drained_while_paused(clean_crawl: AsyncEngine) -> None:
    """The reason resume carries the drained-finish in its own transaction:
    a run whose in-flight tail was the whole remaining queue is closed by
    nothing else — none of its rows will ever close again, and both finish
    paths fence on `running`. Without this, resume hangs the run `running`
    for ever."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a", state="done")
    runs = PostgresRuns(engine)
    assert (await runs.pause_run(run)).transitioned

    # The fence the same transaction relies on: a paused, drained run is
    # closed by neither finish path.
    assert await runs.finish_if_drained(run) is None
    assert await runs.finish_drained() == []
    assert (await run_row(engine, run)).state == "paused"

    outcome = await runs.resume_run(run)

    assert outcome.transitioned is True
    assert outcome.stats is not None, "the drained run completed on resume, not after it"
    assert outcome.stats["pages_crawled"] == 1
    assert (await run_row(engine, run)).state == "completed"


@pytest.mark.parametrize("state", ("running", *TERMINAL), ids=("running", *TERMINAL))
async def test_resume_on_anything_but_paused_misses_and_reports_the_state(
    clean_crawl: AsyncEngine, state: str
) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await mark_run(engine, run, state)

    outcome = await PostgresRuns(engine).resume_run(run)

    assert outcome.transitioned is False
    assert outcome.state == state
    assert (await run_row(engine, run)).state == state


async def test_stop_from_running_reports_the_work_it_did_not_do(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0040's two-statements-one-transaction ordering, on ADR-0041's
    stop: the abandon commits before `_STATS` reads, or the snapshot sees
    the rows as still `pending` and writes `pages_abandoned = 0` — the
    clean finish stop exists to prevent."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await seed_queue_row(engine, run, domain, "https://v.test/b")
    await seed_queue_row(engine, run, domain, "https://v.test/c", state="done")
    item_in_flight = await seed_queue_row(
        engine, run, domain, "https://v.test/d", state="in_flight", attempts=1
    )

    outcome = await PostgresRuns(engine).stop_run(run)

    assert outcome.transitioned is True
    assert outcome.abandoned == 2, "only the pending rows are the work not done"
    row = await run_row(engine, run)
    assert row.state == "stopped"
    # Spec 001 §2 pins the vocabulary; the literal is the contract.
    assert row.stop_reason == "stopped by operator"
    assert row.finished_at is not None
    assert row.stats is not None
    assert row.stats["pages_abandoned"] == 2, "the stats snapshot missed the abandon"
    assert row.stats["pages_crawled"] == 1
    # In-flight rows are untouched: they finish their fetch and close
    # normally, after the snapshot — the stated, bounded cost.
    assert (await queue_row(engine, item_in_flight)).state == QueueItemState.IN_FLIGHT


async def test_stop_from_paused_is_legal(clean_crawl: AsyncEngine) -> None:
    """Forcing resume-then-stop would make rows claimable again for a
    window — a momentary resurrection to achieve the one thing stop must
    not do. The guard admits `paused` directly."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    runs = PostgresRuns(engine)
    assert (await runs.pause_run(run)).transitioned

    outcome = await runs.stop_run(run)

    assert outcome.transitioned is True
    assert outcome.abandoned == 1
    assert (await run_row(engine, run)).state == "stopped"


@pytest.mark.parametrize("state", TERMINAL, ids=TERMINAL)
async def test_stop_on_a_terminal_run_changes_nothing_and_reports_the_state(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """First committer wins; stop's guard simply misses. The fixture parks
    the run terminal with a drained queue, the way a real terminal run
    holds no pending rows."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a", state="done")
    await mark_run(engine, run, state)
    before = await run_row(engine, run)

    outcome = await PostgresRuns(engine).stop_run(run)

    assert outcome.transitioned is False
    assert outcome.state == state
    after = await run_row(engine, run)
    assert after.state == state
    assert after.stop_reason == before.stop_reason, "a missed stop rewrote the reason"


async def test_a_drained_running_run_completes_with_stats(clean_crawl: AsyncEngine) -> None:
    """The `running → completed` edge of spec 001 §2's table, pinned here
    so the table is complete in one file (the crawl-size proof is 1.13's)."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a", state="done")

    stats = await PostgresRuns(engine).finish_if_drained(run)

    assert stats is not None and stats["pages_crawled"] == 1
    assert (await run_row(engine, run)).state == "completed"


async def test_a_cap_halt_fails_the_run_with_its_reason(clean_crawl: AsyncEngine) -> None:
    """The `running → failed` edge (ADR-0040). Pinned once here for the
    table; the breach at crawl size is `test_trap_crawls.py`'s."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    await seed_queue_row(engine, run, domain, "https://v.test/b")

    halt = await PostgresFrontier(engine).halt_run(run, domain, "url cap exceeded: test")

    assert halt.transitioned is True
    assert halt.abandoned == 2
    row = await run_row(engine, run)
    assert row.state == "failed"
    assert row.stop_reason == "url cap exceeded: test"
    assert row.stats is not None and row.stats["pages_abandoned"] == 2


# ---------------------------------------------------------------------------
# 6. The CHECK — every non-completed terminal row names why it ended
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ("stopped", "failed"), ids=("stopped", "failed"))
async def test_the_check_rejects_a_terminal_row_without_a_stop_reason(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """A constraint a future writer can violate silently is not an
    invariant (ADR-0041's rejected alternative): the violation is loud at
    the write, which is where it is cheap to fix."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])

    with pytest.raises(IntegrityError, match="runs_terminal_stop_reason"):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE crawl.runs SET state = CAST(:s AS crawl.run_state) WHERE id = :i"),
                {"s": state, "i": int(run)},
            )


@pytest.mark.parametrize("state", NULL_REASON_OK, ids=NULL_REASON_OK)
async def test_the_check_accepts_a_non_terminal_or_completed_row_without_a_reason(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """`paused` is on the NULL side on purpose — it is resumable, not
    terminal — and `completed` is the one terminal state that may end
    without naming a reason: draining is not a failure."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])

    await mark_run(engine, run, state, reason=None)

    assert (await run_row(engine, run)).state == state


@pytest.mark.parametrize("state", ("stopped", "failed"), ids=("stopped", "failed"))
async def test_a_terminal_row_with_a_reason_is_fine(clean_crawl: AsyncEngine, state: str) -> None:
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])

    await mark_run(engine, run, state, reason="because")

    row = await run_row(engine, run)
    assert (row.state, row.stop_reason) == (state, "because")


# ---------------------------------------------------------------------------
# 7. The completion race — first committer wins, no interleaved state
# ---------------------------------------------------------------------------


async def test_a_finish_waiting_on_an_uncommitted_stop_misses(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """Stop holds the run row's lock mid-transaction; the last closing
    row's finish arrives meanwhile. It must wait for the stop, then find
    `state <> 'running'` and refuse — a stopped run can never be marked
    `completed` by its tail. Without the state fence the finish would
    complete the run the operator had just stopped, under it."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a", state="done")

    stopper = create_async_engine(database_url)
    finisher = create_async_engine(database_url)
    try:
        async with stopper.connect() as a:
            trans = await a.begin()
            await a.execute(_ABANDON_RUN, {"run_id": int(run)})
            await a.execute(_STOP_RUN, {"run_id": int(run), "reason": STOP_REASON_OPERATOR})
            pending = asyncio.create_task(PostgresRuns(finisher).finish_if_drained(run))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await stopper.dispose()
        await finisher.dispose()

    assert waited and not done_early, "the finish did not wait for the stop"
    assert outcome is None, "a finish completed the run over an uncommitted stop"
    row = await run_row(engine, run)
    assert row.state == "stopped"
    assert row.stop_reason == "stopped by operator"


async def test_a_stop_waiting_on_an_uncommitted_finish_misses(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The other order: the run completed first, stop arrives while the
    completion's transaction is still open. Stop's guard misses on the
    committed `completed` state and reports it — a completed run can never
    be stopped, and the CLI prints the refusal, never a lie."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a", state="done")

    finisher = create_async_engine(database_url)
    stopper = create_async_engine(database_url)
    try:
        async with finisher.connect() as a:
            trans = await a.begin()
            await a.execute(_FINISH_IF_DRAINED, {"run_id": int(run)})
            pending = asyncio.create_task(PostgresRuns(stopper).stop_run(run))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await finisher.dispose()
        await stopper.dispose()

    assert waited and not done_early, "the stop did not wait for the finish"
    assert outcome.transitioned is False
    assert outcome.state == "completed"
    row = await run_row(engine, run)
    assert (row.state, row.stop_reason) == ("completed", None)


# ---------------------------------------------------------------------------
# 8. The serialisation — routing and discovery writers vs run transitions
# ---------------------------------------------------------------------------
#
# The fences above say WHAT each writer decides; the locks say the decision
# cannot be made against a run state that is about to change. A stop (or a
# cap halt) committing between a routing writer's unlocked read of
# `runs.state` and its own commit leaves a row `pending` on a terminal run —
# unclaimable (the claim fence holds) but permanently unreported. Both
# halves are pinned here, each as the deterministic interleaving the
# reviewer proved:
#
# - the routing/discovery writers take the run row `FOR SHARE` (release:
#   a preceding statement; sweep: in the expired CTE's locking clause;
#   enqueue: the `run` CTE at the top), and
# - `stop_run`/`halt_run` take it `FOR UPDATE` FIRST, so a routing share
#   lock parks them BEFORE their abandon — without the writer-side lock
#   the abandon runs while the release still holds the row, misses it,
#   and the release commits it `pending` onto the stopped run.
#
# Two engine mechanics, learned from the probes this suite is built on:
# share-vs-share does not conflict, so every `waited` below is observed on
# the EXCLUSIVE side blocking (or the share side blocking behind it); and
# the fixtures' domains must be `active` — a `discovered` domain
# short-circuits the enqueue before the run lock is ever consulted.


async def _claimed_in_flight_row(
    engine: AsyncEngine, run: RunId, domain: DomainId
) -> tuple[ClaimedUrl, int]:
    """Claim the run's one row through the real frontier, so the release
    interleavings drive a genuine lease, and return `(item, item_id)`."""
    f = PostgresFrontier(engine)
    item = await f.claim()
    assert item is not None, "nothing was claimable"
    return item, int(item.id)


async def test_a_release_under_a_parked_stop_routes_pending_and_the_stop_catches_the_row(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """Release holds the run row `FOR SHARE`; the stop parks on its
    `FOR UPDATE` BEFORE its abandon (the writer-side lock). The release
    routes the row `pending` against the still-`running` run and commits;
    the stop wakes, and its abandon — which had not run yet — sees the
    committed `pending` row. The row ends `abandoned`, `abandoned == 1`,
    the run `stopped`: the work is reported, not holed.

    Delete the stop's lock-first and the abandon runs while parked on the
    run row instead: it misses the in-flight row, the release commits it
    `pending` after the stop, and both assertions below fail."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    item, item_id = await _claimed_in_flight_row(engine, run, domain)

    releaser = create_async_engine(database_url)
    stopper = create_async_engine(database_url)
    try:
        async with releaser.connect() as a:
            trans = await a.begin()
            await a.execute(_LOCK_RUN_FOR_RELEASE, {"run_id": int(run)})
            pending = asyncio.create_task(PostgresRuns(stopper).stop_run(run))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            # The share lock held, the stop parked pre-abandon: the release
            # is now free to route and commit under it.
            await a.execute(_RELEASE_QUEUE, {"id": item_id, "lease": item.locked_until})
            await a.execute(_RELEASE_DOMAIN, {"domain_id": int(domain)})
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await releaser.dispose()
        await stopper.dispose()

    assert waited and not done_early, "the stop did not park on the release's share lock"
    assert outcome.transitioned is True
    assert outcome.abandoned == 1, "the stop's abandon missed the released row"
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED
    row = await run_row(engine, run)
    assert row.state == "stopped"
    assert row.stats is not None and row.stats["pages_abandoned"] == 1


async def test_a_release_waiting_on_an_uncommitted_stop_routes_abandoned(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The other order: the stop holds the run row `FOR UPDATE` with its
    transaction open, and the release's preceding `FOR SHARE` must WAIT
    for it, then route against the committed terminal state. Without the
    share lock the release never waits: it routes `pending` against the
    pre-stop snapshot, commits, and the row lands `pending` on a stopped
    run — exactly the hole the serialisation exists to close."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    item, item_id = await _claimed_in_flight_row(engine, run, domain)

    stopper = create_async_engine(database_url)
    releaser = create_async_engine(database_url)
    try:
        async with stopper.connect() as a:
            trans = await a.begin()
            await a.execute(_LOCK_RUN_FOR_STOP, {"run_id": int(run)})
            pending = asyncio.create_task(PostgresFrontier(releaser).release(item))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await a.execute(_ABANDON_RUN, {"run_id": int(run)})
            await a.execute(_STOP_RUN, {"run_id": int(run), "reason": STOP_REASON_OPERATOR})
            await trans.commit()
        released = await asyncio.wait_for(pending, timeout=10)
    finally:
        await stopper.dispose()
        await releaser.dispose()

    assert waited and not done_early, "the release did not wait for the stop"
    assert released is True
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED
    assert (await run_row(engine, run)).state == "stopped"


async def test_a_sweep_waiting_on_an_uncommitted_stop_abandons_the_row(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """An expired lease on a run a stop is transitioning. The sweep's
    `FOR SHARE OF r` — in the expired CTE's locking clause, so the routing
    read and the row's fate are decided under one lock — must wait for the
    stop, then re-read `stopped` (EvalPlanQual) and route `abandoned`,
    never `pending`-on-terminal. Without the share lock the sweep reads
    the pre-stop `running`, routes `pending`, and commits it onto the
    stopped run."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    item_id = await _expired_row(engine, run, domain, "https://v.test/a")

    stopper = create_async_engine(database_url)
    sweeper = create_async_engine(database_url)
    try:
        async with stopper.connect() as a:
            trans = await a.begin()
            await a.execute(_LOCK_RUN_FOR_STOP, {"run_id": int(run)})
            pending = asyncio.create_task(PostgresFrontier(sweeper).sweep_expired_leases())
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await a.execute(_ABANDON_RUN, {"run_id": int(run)})
            await a.execute(_STOP_RUN, {"run_id": int(run), "reason": STOP_REASON_OPERATOR})
            await trans.commit()
        recovered = await asyncio.wait_for(pending, timeout=10)
    finally:
        await stopper.dispose()
        await sweeper.dispose()

    assert waited and not done_early, "the sweep did not wait for the stop"
    assert recovered == 1
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED
    assert (await run_row(engine, run)).state == "stopped"


async def test_an_enqueue_waiting_on_an_uncommitted_stop_inserts_nothing(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The discovery writer: the enqueue's `run` CTE takes the run row
    `FOR SHARE`, so an enqueue arriving behind an uncommitted stop blocks
    BEFORE the insert, wakes on commit, re-reads `stopped`, and inserts
    nothing — `added == 0`, no row `pending` on the terminal run. The
    domain is `active` on purpose: a non-active domain short-circuits the
    insert before the run lock is ever consulted, and the interleaving
    would prove nothing about it."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])

    stopper = create_async_engine(database_url)
    enqueuer = create_async_engine(database_url)
    try:
        async with stopper.connect() as a:
            trans = await a.begin()
            await a.execute(_LOCK_RUN_FOR_STOP, {"run_id": int(run)})
            pending = asyncio.create_task(
                PostgresFrontier(enqueuer).enqueue(
                    run, domain, [("https://v.test/late", 1)], cap=20_000
                )
            )
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await a.execute(_ABANDON_RUN, {"run_id": int(run)})
            await a.execute(_STOP_RUN, {"run_id": int(run), "reason": STOP_REASON_OPERATOR})
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await stopper.dispose()
        await enqueuer.dispose()

    assert waited and not done_early, "the enqueue did not wait for the stop"
    assert (outcome.added, outcome.capped) == (0, False)
    assert await _ids_of_run(engine, run) == [], "a row landed pending on the stopped run"
    assert (await run_row(engine, run)).state == "stopped"


async def test_a_stop_waiting_on_an_uncommitted_enqueue_abandons_its_rows(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The mirror: the enqueue commits first, holding the run row `FOR
    SHARE` until it does, so the stop parks on its `FOR UPDATE` and its
    abandon — which runs only after the enqueue's rows are committed —
    sees them. This is the enqueue's share lock doing the other half of
    its job: the stop's report counts the discovered work, and no
    discovered row survives a stop as `pending`."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    url = "https://v.test/discovered"

    enqueuer = create_async_engine(database_url)
    stopper = create_async_engine(database_url)
    try:
        async with enqueuer.connect() as a:
            trans = await a.begin()
            inserted = (
                await a.execute(
                    _ENQUEUE,
                    {
                        "run_id": int(run),
                        "domain_id": int(domain),
                        "urls": [url],
                        "hashes": [url_hash(url)],
                        "depths": [1],
                        "cap": 20_000,
                    },
                )
            ).one()
            assert inserted.added == 1
            pending = asyncio.create_task(PostgresRuns(stopper).stop_run(run))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await enqueuer.dispose()
        await stopper.dispose()

    assert waited and not done_early, "the stop did not wait for the enqueue"
    assert outcome.transitioned is True
    assert outcome.abandoned == 1, "the stop's abandon never saw the discovered row"
    ids = await _ids_of_run(engine, run)
    assert len(ids) == 1 and (await queue_row(engine, ids[0])).state == QueueItemState.ABANDONED
    assert (await run_row(engine, run)).state == "stopped"


async def test_a_halt_parks_before_its_abandon_and_catches_a_row_released_under_it(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """`halt_run` carries the same writer-side lock as `stop_run` because
    the `failed` edge has the identical shape and the identical hole: a
    release holding the run row `FOR SHARE` must park the halt BEFORE its
    abandon, so the released row is committed `pending` first and the
    halt's domain-scoped abandon catches it."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    item, item_id = await _claimed_in_flight_row(engine, run, domain)

    releaser = create_async_engine(database_url)
    halter = create_async_engine(database_url)
    try:
        async with releaser.connect() as a:
            trans = await a.begin()
            await a.execute(_LOCK_RUN_FOR_RELEASE, {"run_id": int(run)})
            pending = asyncio.create_task(
                PostgresFrontier(halter).halt_run(run, domain, "fixture halt")
            )
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await a.execute(_RELEASE_QUEUE, {"id": item_id, "lease": item.locked_until})
            await a.execute(_RELEASE_DOMAIN, {"domain_id": int(domain)})
            await trans.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await releaser.dispose()
        await halter.dispose()

    assert waited and not done_early, "the halt did not park on the release's share lock"
    assert outcome.transitioned is True
    assert outcome.abandoned == 1, "the halt's abandon missed the released row"
    assert (await queue_row(engine, item_id)).state == QueueItemState.ABANDONED
    assert (await run_row(engine, run)).state == "failed"


# ---------------------------------------------------------------------------
# 9. The transitions replay — every move writes its `run_state` event
#     (BUILD_PLAN 2.8, ADR-0042)
# ---------------------------------------------------------------------------


async def _run_state_events(engine: AsyncEngine, run: RunId) -> list[dict[str, Any]]:
    """The run's `run_state` payloads, in seq order — the rows 3.6's SSE
    replay will send, and nothing else (each transition's event is the
    whole point here, not the page/progress noise around it)."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT seq, payload FROM crawl.run_events "
                "WHERE run_id = :r AND kind = 'run_state' ORDER BY seq"
            ),
            {"r": int(run)},
        )
    return [dict(r.payload) for r in rows]


async def test_every_operator_transition_writes_its_run_state_event(
    clean_crawl: AsyncEngine,
) -> None:
    """Pause, resume, stop — each move leaves the event that replays it,
    with spec 005 §3's shape: `state` always, `stop_reason` on the stop,
    `stats` on the terminal transition only. And a fenced miss (a pause of
    a run already paused) emits nothing — the event says a transition
    happened, so a non-transition must not write one."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    # A pending row keeps the run undrained through pause and resume, so
    # the stop at the end is the only terminal transition.
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    runs = PostgresRuns(engine)

    assert (await runs.pause_run(run)).transitioned
    assert not (await runs.pause_run(run)).transitioned, "the fixture re-paused"
    assert (await runs.resume_run(run)).transitioned
    assert (await runs.stop_run(run)).transitioned

    events = await _run_state_events(engine, run)
    assert [e["state"] for e in events] == ["paused", "running", "stopped"]
    assert set(events[0]) == {"state"}, "pause is resumable: no stats, no reason"
    assert set(events[1]) == {"state"}, "resume is not terminal: no stats"
    assert set(events[2]) == {"state", "stop_reason", "stats"}
    assert events[2]["stop_reason"] == STOP_REASON_OPERATOR
    assert events[2]["stats"]["pages_crawled"] == 0, "stats is the transition-time snapshot"


async def test_resume_completing_a_drained_run_writes_both_events(
    clean_crawl: AsyncEngine,
) -> None:
    """A run that drained while paused is completed by the resume itself,
    in the same transaction — so both the `running` and the `completed`
    event exist, `completed` carrying the stats snapshot, with nothing in
    between."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    await seed_queue_row(engine, run, domain, "https://v.test/a")
    runs = PostgresRuns(engine)

    assert (await runs.pause_run(run)).transitioned
    async with engine.begin() as conn:
        # The in-flight tail was the whole remaining queue: it closes done
        # while the run is paused, leaving nothing to claim.
        await conn.execute(
            sa.text("UPDATE crawl.crawl_queue SET state = 'done' WHERE run_id = :r"),
            {"r": int(run)},
        )

    outcome = await runs.resume_run(run)
    assert outcome.stats is not None, "the fixture did not drain the run"

    events = await _run_state_events(engine, run)
    assert [e["state"] for e in events] == ["paused", "running", "completed"]
    assert set(events[2]) == {"state", "stats"}
    assert events[2]["stats"]["pages_crawled"] == 1


async def test_finish_drained_writes_the_completed_event_for_runs_no_worker_owns(
    clean_crawl: AsyncEngine,
) -> None:
    """The unowned finish: a worker SIGKILLed on the run's last row leaves
    the sweep to retire it, and no one closes it — the transition emits the
    terminal event itself (ADR-0042's answer to "who emits for a run
    finished by `finish_drained`"). Every run the statement finishes gets
    its own row, in the statement's own transaction."""
    engine = clean_crawl
    finished: list[RunId] = []
    for n in range(2):
        domain = await seed_domain(engine, f"two-drains-{n}.test")
        run = await seed_run(engine, [int(domain)])
        await seed_queue_row(engine, run, domain, f"https://v.test/{n}")
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE crawl.crawl_queue SET state = 'done' WHERE run_id = :r"),
                {"r": int(run)},
            )
        finished.append(run)

    completed = await PostgresRuns(engine).finish_drained()
    assert {r for r, _ in completed} == set(finished), "the fixture finished nothing"

    for run in finished:
        events = await _run_state_events(engine, run)
        assert [e["state"] for e in events] == ["completed"]
        assert set(events[0]) == {"state", "stats"}


async def test_halt_run_writes_its_failed_event_with_the_reason_and_stats(
    clean_crawl: AsyncEngine,
) -> None:
    """2.5's cap-halt seam replayed: the `failed` edge's event carries the
    stop_reason the operator will read (the cap, named) and the
    transition-time stats snapshot — the same one written to `runs.stats`."""
    engine = clean_crawl
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    for n in range(3):
        await seed_queue_row(engine, run, domain, f"https://v.test/{n}")

    reason = "fixture halt"
    halt = await PostgresFrontier(engine).halt_run(run, domain, reason)
    assert halt.transitioned

    events = await _run_state_events(engine, run)
    assert [e["state"] for e in events] == ["failed"]
    assert set(events[0]) == {"state", "stop_reason", "stats"}
    assert events[0]["stop_reason"] == reason
    # ADR-0040's ordering: the stats read runs after the abandon, so the
    # event replays the same number `runs.stats` carries.
    assert events[0]["stats"]["pages_abandoned"] == 3
