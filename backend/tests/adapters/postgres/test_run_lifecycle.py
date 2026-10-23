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
the subprocess) lives in `tests/scheduler/test_run_lifecycle.py`.

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

from spydra.adapters.postgres.frontier import MAX_ATTEMPTS, PostgresFrontier
from spydra.adapters.postgres.runs import (
    _ABANDON_RUN,
    _FINISH_IF_DRAINED,
    _STOP_RUN,
    STOP_REASON_OPERATOR,
    PostgresRuns,
)
from spydra.domain.ids import DomainId, RunId
from spydra.ports.frontier import QueueItemState
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
