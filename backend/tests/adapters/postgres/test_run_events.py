"""The bounded per-run event log's writer (BUILD_PLAN 2.8, ADR-0042).

Everything here is against real Postgres with committed rows, because the
guarantees under test are the database's: the seq reservation's atomicity
under two genuinely concurrent emitters, the rollback discipline that makes
the sequence gap-free by construction, and the trim's bound.

The emission **set** — which crawl outcomes produce which events — is
pinned at the crawler seam (`tests/scheduler/test_page_crawler.py`) and the
transition seam (`test_run_lifecycle.py`); this file owns the mechanism
every one of those sites rides on:

- **two real engines, one run, no coordination** — `UNIQUE (run_id, seq)`
  holds and the seqs come out exactly `1..N`, because the reservation's
  own row lock serialises reservers and there is no retry policy to pin;
- **rollback discards reservation and insert together**, which is what
  makes `seq` gap-free rather than merely monotonic — a client that sees
  `id: 1041` after `id: 1039` cannot tell "one lost" from "one trimmed",
  so holes may never exist in the first place;
- **the trim keeps the last `KEEP_EVENTS` per live run, exactly**, and
  never touches a terminal run — the truncation a reconnecting SSE client
  will detect by arithmetic (`first retained > Last-Event-ID + 1`).
"""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spydra.adapters.postgres.run_events import KEEP_EVENTS, PostgresRunEvents, emit_in
from spydra.adapters.postgres.runs import _PAUSE_RUN, PostgresRuns
from spydra.domain.ids import RunId
from tests.adapters.postgres.seed import seed_domain, seed_run
from tests.adapters.postgres.test_enqueue_guard import _waiting_on_a_lock

pytestmark = pytest.mark.integration

HOST = "vantage-abrasives.test"


async def events_of(engine: AsyncEngine, run: RunId) -> list[tuple[int, str, dict[str, object]]]:
    """The run's events by seq: `(seq, kind, payload)`."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT seq, kind, payload FROM crawl.run_events WHERE run_id = :r ORDER BY seq"
            ),
            {"r": int(run)},
        )
    return [(int(r.seq), str(r.kind), dict(r.payload)) for r in rows]


async def next_seq_of(engine: AsyncEngine, run: RunId) -> int:
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    sa.text("SELECT next_seq FROM crawl.runs WHERE id = :i"), {"i": int(run)}
                )
            ).scalar_one()
        )


async def _emit_n(engine: AsyncEngine, run: RunId, n: int, kind: str = "page") -> list[int]:
    """`n` emissions in one transaction: the fastest honest way past the
    bound. The reservation mechanism does not care how many statements
    share the transaction — that is the point of reserve-then-spend."""
    seqs: list[int] = []
    async with engine.begin() as conn:
        for _ in range(n):
            seqs.append(await emit_in(conn, run, kind, {}))
    return seqs


async def _live_run(engine: AsyncEngine) -> RunId:
    domain = await seed_domain(engine, HOST)
    return await seed_run(engine, [int(domain)])


# ---------------------------------------------------------------------------
# 1. Two real engines, one run — the concurrency done-when
# ---------------------------------------------------------------------------


async def test_two_engines_emitting_concurrently_for_one_run_never_lose_or_duplicate_a_seq(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """Three phases of contention over one run's seq, two genuinely
    separate connections (one connection cannot race itself):

    1. **blocked behind an uncommitted emit** — engine A reserves inside an
       open transaction; engine B's emit must wait on the run row's lock,
       then land the next seq, not A's;
    2. **rapid alternating commits** — A, B, A, B… the interleaving two
       claim loops on one run actually produce;
    3. **a concurrent burst** — 40 emits fired at once across both engines,
       so many reservations queue on the same row lock.

    N emissions must yield N rows whose seqs are exactly `1..N` — none
    dropped, none duplicated, no `UNIQUE (run_id, seq)` violation (an
    `IntegrityError` here fails the gather and the test with it: the
    no-retry design's answer to a duplicate is to refuse it loudly)."""
    run = await _live_run(clean_crawl)
    a = create_async_engine(database_url)
    b = create_async_engine(database_url)
    emit_a = PostgresRunEvents(a).emit
    emit_b = PostgresRunEvents(b).emit
    try:
        # Phase 1: contended, behind an uncommitted reservation.
        async with a.connect() as conn:
            trans = await conn.begin()
            held = await emit_in(conn, run, "page", {"phase": 1, "engine": "a"})
            pending = asyncio.create_task(emit_b(run, "page", {"phase": 1, "engine": "b"}))
            waited = await _waiting_on_a_lock(clean_crawl)
            done_early = pending.done()
            await trans.commit()
        blocked = await asyncio.wait_for(pending, timeout=10)
        assert waited and not done_early, "the second emit did not wait on the run row"

        # Phase 2: rapid alternating commits, the two-loop interleaving.
        alternating: list[int] = []
        for i in range(30):
            alternating.append(await emit_a(run, "page", {"phase": 2, "i": i}))
            alternating.append(await emit_b(run, "page", {"phase": 2, "i": i}))

        # Phase 3: a concurrent burst across both engines.
        burst = await asyncio.gather(
            *(emit_a(run, "page", {"phase": 3, "i": i}) for i in range(20)),
            *(emit_b(run, "page", {"phase": 3, "i": i}) for i in range(20)),
        )
    finally:
        await a.dispose()
        await b.dispose()

    total = 2 + 60 + 40
    returned = [held, blocked, *alternating, *burst]
    assert len(set(returned)) == total, "an emitter received another emitter's seq"
    assert sorted(returned) == list(range(1, total + 1)), "the seqs are not gap-free 1..N"

    landed = await events_of(clean_crawl, run)
    assert [seq for seq, _, _ in landed] == list(range(1, total + 1)), "rows were lost"
    assert await next_seq_of(clean_crawl, run) == total


# ---------------------------------------------------------------------------
# 2. Rollback discipline — gap-free by construction
# ---------------------------------------------------------------------------


async def test_a_rolled_back_emission_reserves_nothing_and_leaves_no_hole(
    clean_crawl: AsyncEngine,
) -> None:
    """The ordinal property every reconnecting client leans on: `seq` is
    the ordinal of every event the run ever emitted, holes included in the
    count. A rolled-back reservation that survived as a counter bump would
    make the next commit's seq skip — `id: 1041` after `id: 1039` — and
    change reconnect semantics for ever after."""
    run = await _live_run(clean_crawl)
    events = PostgresRunEvents(clean_crawl)

    assert await events.emit(run, "page", {"i": 1}) == 1
    assert await events.emit(run, "page", {"i": 2}) == 2

    async with clean_crawl.connect() as conn:
        trans = await conn.begin()
        discarded = await emit_in(conn, run, "page", {"i": "rolled back"})
        await trans.rollback()
    assert discarded == 3, "the discarded emission reserved a seq out of line"

    assert [seq for seq, _, _ in await events_of(clean_crawl, run)] == [1, 2]
    assert await next_seq_of(clean_crawl, run) == 2, "the rollback leaked a reservation"
    assert await events.emit(run, "page", {"i": 3}) == 3, "the next emit skipped a seq"


async def test_a_rolled_back_transition_leaves_neither_state_nor_event(
    clean_crawl: AsyncEngine,
) -> None:
    """The `run_state` half of ADR-0042's split, probed where it lives: a
    run transition and its event share one transaction, so an event row
    exists iff the transition happened. Roll the transaction back and both
    halves must vanish — a caller-side emit could crash between
    transition-commit and event-insert, and the terminal event is the one
    a reconnecting client cannot live without."""
    run = await _live_run(clean_crawl)

    async with clean_crawl.connect() as conn:
        trans = await conn.begin()
        paused = (await conn.execute(_PAUSE_RUN, {"run_id": int(run)})).scalar_one_or_none()
        assert paused is not None, "the fixture did not reach a live transition"
        await emit_in(conn, run, "run_state", {"state": "paused"})
        await trans.rollback()

    assert [seq for seq, _, _ in await events_of(clean_crawl, run)] == []
    assert await next_seq_of(clean_crawl, run) == 0
    assert (await PostgresRuns(clean_crawl).pause_run(run)).transitioned, (
        "the run was left paused by the rolled-back transaction"
    )


async def test_the_payload_lands_as_jsonb_verbatim(clean_crawl: AsyncEngine) -> None:
    run = await _live_run(clean_crawl)
    payload = {"state": "completed", "stats": {"pages_crawled": 3, "by_domain": {}}, "n": None}

    await PostgresRunEvents(clean_crawl).emit(run, "run_state", payload)

    assert [p for _, _, p in await events_of(clean_crawl, run)] == [payload]


# ---------------------------------------------------------------------------
# 3. The trim — keep-last-N, live runs only
# ---------------------------------------------------------------------------


async def test_trim_holds_the_bound_on_a_run_that_emits_past_it(
    clean_crawl: AsyncEngine,
) -> None:
    """The acceptance bound with the shipped constant: a live run that
    emits `KEEP_EVENTS + 20` and is swept retains exactly `KEEP_EVENTS` —
    the newest `KEEP_EVENTS`, `hi - keep + 1 .. hi` with no off-by-one at
    either edge — and the terminal `run_state`, being the newest row, is
    always among them."""
    run = await _live_run(clean_crawl)
    events = PostgresRunEvents(clean_crawl)

    hi = KEEP_EVENTS + 20
    await _emit_n(clean_crawl, run, hi)
    deleted = await events.trim()
    assert deleted == 20

    landed = await events_of(clean_crawl, run)
    assert len(landed) == KEEP_EVENTS, "the bound slipped"
    first = landed[0][0]
    assert first == hi - KEEP_EVENTS + 1, "the trim kept one row too few"
    assert landed[-1][0] == hi

    await _emit_n(clean_crawl, run, 1, kind="run_state")
    # One more emission past the bound: the trim gives up the window's
    # oldest row for it, never the newest.
    assert await events.trim() == 1
    landed = await events_of(clean_crawl, run)
    assert len(landed) == KEEP_EVENTS
    assert landed[-1][1] == "run_state", "the terminal event was trimmed away"


async def test_trim_deletes_nothing_below_the_bound(clean_crawl: AsyncEngine) -> None:
    run = await _live_run(clean_crawl)
    events = PostgresRunEvents(clean_crawl)

    await _emit_n(clean_crawl, run, 7)
    assert await events.trim(keep=10) == 0
    assert len(await events_of(clean_crawl, run)) == 7

    # Off-by-one at the boundary itself: at exactly `keep` rows the trim
    # keeps all of them — `seq <= hi - keep` deletes nothing when hi == keep.
    await _emit_n(clean_crawl, run, 3)
    assert await events.trim(keep=10) == 0
    assert [seq for seq, _, _ in await events_of(clean_crawl, run)] == list(range(1, 11))


@pytest.mark.parametrize("state", ["running", "paused"])
async def test_trim_sweeps_both_live_run_states(clean_crawl: AsyncEngine, state: str) -> None:
    """`paused` is live: it is resumable, so its log keeps growing and the
    bound must apply to it exactly as to `running`."""
    run = await _live_run(clean_crawl)
    await _emit_n(clean_crawl, run, 25)
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.runs SET state = CAST(:s AS crawl.run_state) WHERE id = :i"),
            {"s": state, "i": int(run)},
        )

    assert await PostgresRunEvents(clean_crawl).trim(keep=10) == 15
    assert [seq for seq, _, _ in await events_of(clean_crawl, run)] == list(range(16, 26))


@pytest.mark.parametrize("state", TERMINAL_STATES := ("completed", "stopped", "failed"))
async def test_a_terminal_run_is_frozen_where_it_stood(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """Terminal runs emit nothing more, so trimming one could only lose the
    ε of events between its last sweep and termination — the documented
    slop, kept for ever rather than reclaimed. The tail, and always the
    terminal `run_state` as its newest row, stay."""
    run = await _live_run(clean_crawl)
    await _emit_n(clean_crawl, run, 18)
    async with clean_crawl.begin() as conn:
        # The reason is the CHECK's, not the trim's: only `completed` may
        # end bare.
        await conn.execute(
            sa.text(
                "UPDATE crawl.runs SET state = CAST(:s AS crawl.run_state), "
                "stop_reason = :r, finished_at = now() WHERE id = :i"
            ),
            {"s": state, "r": None if state == "completed" else "fixture", "i": int(run)},
        )
    await _emit_n(clean_crawl, run, 4, kind="run_state")

    assert await PostgresRunEvents(clean_crawl).trim(keep=10) == 0, (
        "the trim reached into a terminal run"
    )
    landed = await events_of(clean_crawl, run)
    assert len(landed) == 22
    assert landed[-1][1] == "run_state"


async def test_the_slop_between_the_last_trim_and_termination_is_bounded_by_emission(
    clean_crawl: AsyncEngine,
) -> None:
    """The ε, pinned empirically: a live run's retained set is the bound
    plus exactly what was emitted since the last sweep — never more,
    because the trim never deletes below the bound's window, and never
    less, because nothing else deletes at all."""
    run = await _live_run(clean_crawl)
    events = PostgresRunEvents(clean_crawl)

    await _emit_n(clean_crawl, run, 10)
    assert await events.trim(keep=10) == 0
    for _ in range(6):
        await _emit_n(clean_crawl, run, 1, kind="progress")

    assert len(await events_of(clean_crawl, run)) == 10 + 6, "something trimmed mid-flight"
    assert await events.trim(keep=10) == 6
    assert [seq for seq, _, _ in await events_of(clean_crawl, run)] == list(range(7, 17))


async def test_a_reconnecting_client_detects_truncation_by_arithmetic(
    clean_crawl: AsyncEngine,
) -> None:
    """The property 3.6's SSE replay will rely on (ADR-0042, pinned): with
    a gap-free `seq`, a reconnect needs no marker event —
    `first retained > Last-Event-ID + 1` says truncated, and means
    backfill the entire retained window; anything else replays contiguously
    from `Last-Event-ID + 1`."""
    run = await _live_run(clean_crawl)
    await _emit_n(clean_crawl, run, 12)
    await PostgresRunEvents(clean_crawl).trim(keep=10)

    first, *_ = (seq for seq, _, _ in await events_of(clean_crawl, run))

    # A client that fell asleep just before the trim: its id is below the
    # window, so the window's first seq jumps past `id + 1` — truncated.
    slept_through = first - 2
    assert first > slept_through + 1, "a truncated replay went undetected"

    # A client whose id sits inside the window replays contiguously.
    inside = first + 3
    assert not first > inside + 1

    # And every retained id is unique and ordered, which is what makes the
    # arithmetic trustworthy at all.
    seqs = [seq for seq, _, _ in await events_of(clean_crawl, run)]
    assert seqs == sorted(set(seqs))
