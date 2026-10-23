"""The end of a run (BUILD_PLAN 1.13, spec 009 §5).

A run is finished when its queue has nothing left to claim and nothing in
flight. No process owns "the run" (any worker can close its last row), so the
finish is one guarded `UPDATE` that only the first worker to see the drained
queue gets a row back from. That is the one that logs it.

**`stats` is computed in the same statement**, from the rows themselves
rather than from counters a worker kept: spec 009 §5 wants it populated "on
completion, stop and failure alike", and in-process counters die with the
process that held them. `2.x`'s stop and failure paths reuse `_STATS`.

The operator-driven lifecycle (`pause_run`, `resume_run`, `stop_run`,
BUILD_PLAN 2.7 / ADR-0041) also lives here: this file owns `_STATS` and
both finish paths, and `halt_run`-on-Frontier was a crawler-caller
convenience, not the pattern. The Frontier port is unchanged — the worker
never calls these; the CLI (`spydra.runctl`) and 3.4's API wrap this
adapter directly.
"""

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from spydra.domain.ids import RunId

# Spec 009 §2's shape, for the keys phase 1 can know. `assets_downloaded`,
# `asset_bytes` and `dedupe_rate` arrive with the asset pool (5.2), and
# `validation_pass_rate` with the reports (5.7); `assets_enqueued` stands in
# until then. `by_strategy` counts the rung that produced the fields (the
# `extraction_rung` column, so a static fallback still counts as the rung it
# used), and `failed` is the rows that never produced an observation.
_STATS = """
jsonb_build_object(
    'pages_crawled', (SELECT count(*) FROM crawl.crawl_queue
                      WHERE run_id = :run_id AND state = 'done'),
    'pages_failed', (SELECT count(*) FROM crawl.crawl_queue
                     WHERE run_id = :run_id AND state = 'failed'),
    'pages_abandoned', (SELECT count(*) FROM crawl.crawl_queue
                        WHERE run_id = :run_id AND state = 'abandoned'),
    'pages_changed', (SELECT count(*) FROM crawl.page_observations
                      WHERE run_id = :run_id AND NOT unchanged AND content_hash IS NOT NULL),
    'empty_extractions', (SELECT count(*) FROM crawl.page_observations
                          WHERE run_id = :run_id AND empty_extraction),
    'assets_enqueued', (SELECT count(*) FROM crawl.asset_queue WHERE run_id = :run_id),
    'by_strategy', (
        SELECT coalesce(jsonb_object_agg(rung, n), '{}'::jsonb)
        FROM (
            SELECT coalesce(extraction_rung, 'none') AS rung, count(*) AS n
            FROM crawl.page_observations WHERE run_id = :run_id GROUP BY 1
            UNION ALL
            SELECT 'failed', count(*) FROM crawl.crawl_queue
            WHERE run_id = :run_id AND state = 'failed'
        ) s
    ),
    'by_domain', (
        SELECT coalesce(jsonb_object_agg(d.host, jsonb_build_object(
                   'crawled', s.crawled, 'failed', s.failed)), '{}'::jsonb)
        FROM (
            SELECT domain_id,
                   count(*) FILTER (WHERE state = 'done') AS crawled,
                   count(*) FILTER (WHERE state = 'failed') AS failed
            FROM crawl.crawl_queue WHERE run_id = :run_id GROUP BY domain_id
        ) s
        JOIN crawl.domains d ON d.id = s.domain_id
    ),
    'duration_s', (SELECT round(extract(epoch FROM now() - started_at))::int
                   FROM crawl.runs WHERE id = :run_id)
)
"""

_FINISH_IF_DRAINED = sa.text(
    f"""
UPDATE crawl.runs
SET state = 'completed', finished_at = now(), stats = {_STATS}
WHERE id = :run_id
  AND state = 'running'
  AND NOT EXISTS (
      SELECT 1 FROM crawl.crawl_queue
      WHERE run_id = :run_id AND state IN ('pending', 'in_flight')
  )
RETURNING stats
"""
)


# Every running run whose queue has drained. For the lease sweep: a row it
# retires to `failed` (a worker SIGKILLed on the run's last row, third
# attempt) is closed by no worker, so without this the run stayed `running`
# for ever.
_FINISH_DRAINED = sa.text(
    f"""
UPDATE crawl.runs r
SET state = 'completed', finished_at = now(),
    stats = {_STATS.replace(":run_id", "r.id")}
WHERE r.state = 'running'
  -- A run that has not enqueued anything yet is not drained, it is new.
  AND EXISTS (SELECT 1 FROM crawl.crawl_queue WHERE run_id = r.id)
  AND NOT EXISTS (
      SELECT 1 FROM crawl.crawl_queue
      WHERE run_id = r.id AND state IN ('pending', 'in_flight')
  )
RETURNING r.id, r.stats
"""
)


# --- Operator-driven run lifecycle (BUILD_PLAN 2.7, ADR-0041) ---------------
#
# Every transition is a guarded UPDATE: the predicate on `state` is the
# whole state machine, and whichever guarded writer commits first wins —
# stop fences on `running|paused`, both finish paths fence on `running`, so
# a stopped run can never be completed by its last closing row and a
# completed run can never be stopped. There is deliberately no
# domain/lifecycle.py pure function for runs (contrast domains, spec 001
# §2): the callers are SQL transactions, and a pure function plus a
# separate write is the check-then-act race these predicates exist to
# prevent.

_PAUSE_RUN = sa.text(
    """
    UPDATE crawl.runs SET state = 'paused'
    WHERE id = :run_id AND state = 'running'
    RETURNING id
    """
)

_RESUME_RUN = sa.text(
    """
    UPDATE crawl.runs SET state = 'running'
    WHERE id = :run_id AND state = 'paused'
    RETURNING id
    """
)

# Run-scoped, no domain filter: stop is operator-scoped over the whole run,
# all its domains (ADR-0041) — unlike `_HALT_RUN`'s one-domain abandon,
# which is a defect signal about that domain's rules. Unconditional: on a
# run already terminal it is at worst a repair of the terminal invariant,
# and the guarded UPDATE below decides whether this call stopped anything.
_ABANDON_RUN = sa.text(
    """
    UPDATE crawl.crawl_queue SET state = 'abandoned'
    WHERE run_id = :run_id AND state = 'pending'
    """
)

# The serialisation's other half (ADR-0041). `FOR SHARE` in the routing
# writers only narrows the window unless the terminal writer takes the run
# row exclusively BEFORE its abandon: the abandon (first statement, queue
# rows only) would otherwise run while a release holds the row `in_flight`,
# miss it, and the release would commit it `pending` onto the just-stopped
# run. With this lock first, the routing writer either commits before it —
# and the abandon sees the returned `pending` row — or waits and reads the
# terminal state. Guarded by the same predicate as the transition itself,
# so a run already terminal locks nothing.
_LOCK_RUN_FOR_STOP = sa.text(
    """
SELECT id FROM crawl.runs
WHERE id = :run_id AND state IN ('running', 'paused')
FOR UPDATE
"""
)

_STOP_RUN = sa.text(
    f"""
    UPDATE crawl.runs
    SET state = 'stopped', stop_reason = :reason, finished_at = now(),
        stats = {_STATS}
    WHERE id = :run_id AND state IN ('running', 'paused')
    RETURNING stats
    """
)

_RUN_STATE = sa.text(
    # ::text so the enum cannot arrive as anything but a str
    "SELECT state::text FROM crawl.runs WHERE id = :run_id"
)

# Spec 001 §2's vocabulary. The only non-completed terminal paths that can
# fire today are this and 2.5's cap breach; the CHECK constraint keeps it
# that way structurally.
STOP_REASON_OPERATOR = "stopped by operator"


@dataclass(frozen=True, slots=True)
class RunTransition:
    """An operator-driven run transition's outcome (ADR-0041), mirroring
    `RunHalt`: `transitioned` is True only for the call whose guarded UPDATE
    moved the run, and on a miss `state` is the run's actual state (None
    when no such run) so the CLI reports a refusal, never a lie. `stats` is
    set only when the call itself finished the run (stop always; resume of
    a run that drained while paused); `abandoned` is stop's work-not-done
    count."""

    transitioned: bool
    state: str | None = None
    abandoned: int = 0
    stats: dict[str, Any] | None = None


async def _run_state(conn: AsyncConnection, run_id: RunId) -> str | None:
    return (await conn.execute(_RUN_STATE, {"run_id": int(run_id)})).scalar_one_or_none()


class PostgresRuns:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def pause_run(self, run_id: RunId) -> RunTransition:
        """`running → paused` (ADR-0041). A dequeue freeze: no queue row is
        touched, no `stop_reason` written — paused is resumable, not
        terminal. Claims stop via the claim fence; in-flight rows finish
        their fetch and close normally, and their discovery still enqueues.
        """
        async with self._engine.begin() as conn:
            paused = (await conn.execute(_PAUSE_RUN, {"run_id": int(run_id)})).scalar_one_or_none()
            state = None if paused is not None else await _run_state(conn, run_id)
        return RunTransition(transitioned=paused is not None, state=state)

    async def resume_run(self, run_id: RunId) -> RunTransition:
        """`paused → running`, then the drained check in the SAME transaction.

        A run that drained while paused — its in-flight tail was the whole
        remaining queue — is closed by nothing else: none of its rows will
        ever close again, and `finish_if_drained` fires only after a row
        closes. Without this, resume hangs the run `running` for ever. With
        it, resume either finds work (the run stays `running`, claims
        resume) or completes it with stats, immediately. The finish stays
        fenced on `state = 'running'`, which this transaction just set.
        """
        async with self._engine.begin() as conn:
            resumed = (
                await conn.execute(_RESUME_RUN, {"run_id": int(run_id)})
            ).scalar_one_or_none()
            if resumed is None:
                return RunTransition(transitioned=False, state=await _run_state(conn, run_id))
            stats = (
                await conn.execute(_FINISH_IF_DRAINED, {"run_id": int(run_id)})
            ).scalar_one_or_none()
        return RunTransition(
            transitioned=True,
            stats=dict(stats) if stats is not None else None,
        )

    async def stop_run(self, run_id: RunId) -> RunTransition:
        """`running|paused → stopped`, pending rows abandoned first
        (ADR-0041, on ADR-0040's ordering).

        Two statements, one transaction, and the order is load-bearing: a
        stats subquery beside the abandon in one data-modifying CTE would
        read the pre-abandon snapshot and write `pages_abandoned = 0` — the
        clean finish stop exists to prevent. The second statement sees the
        first's writes. In-flight rows are untouched: they finish their
        fetch and close `done` after the snapshot; that tail is bounded by
        workers × `max_concurrency` and is the stated snapshot cost, same
        as ADR-0040's breach halt. Stop from `paused` is legal — forcing
        resume-then-stop would make rows claimable again for a window, a
        momentary resurrection to achieve the one thing stop must not do.

        Three statements now: the run-row `FOR UPDATE` first (see
        `_LOCK_RUN_FOR_STOP`), then the two ADR-0040 ordered ones. The
        lock is what serialises the release/sweep routing against this
        transition; the abandon-then-stats order is unchanged.
        """
        async with self._engine.begin() as conn:
            await conn.execute(_LOCK_RUN_FOR_STOP, {"run_id": int(run_id)})
            abandoned = await conn.execute(_ABANDON_RUN, {"run_id": int(run_id)})
            stats = (
                await conn.execute(
                    _STOP_RUN,
                    {"run_id": int(run_id), "reason": STOP_REASON_OPERATOR},
                )
            ).scalar_one_or_none()
            state = None if stats is not None else await _run_state(conn, run_id)
        return RunTransition(
            transitioned=stats is not None,
            abandoned=int(abandoned.rowcount),
            stats=dict(stats) if stats is not None else None,
            state=state,
        )

    async def finish_if_drained(self, run_id: RunId) -> dict[str, Any] | None:
        """The run's stats if THIS call finished it, else `None`."""
        async with self._engine.begin() as conn:
            stats = (
                await conn.execute(_FINISH_IF_DRAINED, {"run_id": int(run_id)})
            ).scalar_one_or_none()
        return dict(stats) if stats is not None else None

    async def finish_drained(self) -> list[tuple[RunId, dict[str, Any]]]:
        """Finish every running run with nothing left to claim; the runs
        THIS call finished, with their stats."""
        async with self._engine.begin() as conn:
            rows = (await conn.execute(_FINISH_DRAINED)).all()
        return [(RunId(row.id), dict(row.stats)) for row in rows]
