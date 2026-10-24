"""The bounded per-run event log's writer (BUILD_PLAN 2.8, ADR-0042).

`run_events` has existed since 1.1 with nothing writing it. This is the
writer: a per-run counter on `runs.next_seq` reserved atomically, the
in-transaction helper the run transitions emit `run_state` through, and the
sweep's trim.

**Why a counter column and not `max(seq)+1`.** Reservation is one
``UPDATE .. RETURNING`` on the run row — the UPDATE's own row lock
serialises reservers, so no retry policy is needed and duplicates cannot
occur. Reservation and insert share the caller's transaction, so a rollback
discards both and **`seq` is monotonic AND gap-free by construction**: it is
the ordinal of every event the run has ever emitted. Gap-free is deliberate,
not incidental — SSE reconnect semantics. A client that sees `id: 1041`
after `id: 1039` cannot tell "one lost" from "one trimmed"; gap-free makes
truncation detectable by arithmetic (first delivered `id:` >
`Last-Event-ID + 1`) with no protocol change and no synthetic marker event.

**Adapter-direct, no port** (ADR-0042, on 2.7's precedent): the worker
already consumes `PostgresRuns` and the other repositories directly.
Frontier is a port because it is the reversible-Postgres decision
(ADR-0002/0008), not because everything the worker touches is one; a
one-implementation port is an untested abstraction.
"""

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from spydra.domain.ids import RunId

# The user's bound: keep the last 5,000 events per run (ADR-0012 called this
# "a real piece of work"). A knob, tuned later against real runs — never a
# correctness property.
KEEP_EVENTS = 5_000

_RESERVE_SEQ = sa.text(
    "UPDATE crawl.runs SET next_seq = next_seq + 1 WHERE id = :run_id RETURNING next_seq"
)

_INSERT_EVENT = sa.text(
    """
    INSERT INTO crawl.run_events (run_id, seq, kind, payload)
    VALUES (:run_id, :seq, :kind, CAST(:payload AS jsonb))
    """
)

# Live runs only: a terminal run emits nothing more, so trimming it could
# only lose the ε of events between its last sweep trim and termination.
# Frozen where it stood, the newest row — the terminal `run_state` — is
# always retained.
_TRIM = sa.text(
    """
    DELETE FROM crawl.run_events e
    USING (SELECT e2.run_id, max(e2.seq) AS hi
           FROM crawl.run_events e2
           JOIN crawl.runs r ON r.id = e2.run_id
              AND r.state IN ('running', 'paused')
           GROUP BY e2.run_id) m
    WHERE e.run_id = m.run_id AND e.seq <= m.hi - :keep
    """
)


async def emit_in(conn: AsyncConnection, run_id: RunId, kind: str, payload: dict[str, Any]) -> int:
    """Reserve a seq and insert, on the caller's open transaction. Returns
    the seq.

    The transactional half of ADR-0042's split: the run transitions call
    this on the connection they already hold — the guarded UPDATE has the
    run row locked, so the reservation costs nothing, and a `run_state` row
    exists iff the transition happened. A caller-side emit could crash
    between transition-commit and event-insert and lose the terminal event
    for ever: the one event a reconnecting client cannot live without.
    """
    seq = (await conn.execute(_RESERVE_SEQ, {"run_id": int(run_id)})).scalar_one()
    await conn.execute(
        _INSERT_EVENT,
        {
            "run_id": int(run_id),
            "seq": seq,
            "kind": kind,
            "payload": json.dumps(payload),
        },
    )
    return int(seq)


class PostgresRunEvents:
    """Emit outside a transition, and the maintenance trim."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def emit(self, run_id: RunId, kind: str, payload: dict[str, Any]) -> int:
        """The projected half of ADR-0042's split: `page`, `progress` and
        `domain_state`, each in its own short transaction after the durable
        write it projects. Losing one to a crash is acceptable — the rows
        are the facts; the event is the SSE projection. No coupling to the
        queue transaction: the observation path must not hold locks while
        writing a different table.

        Deliberately no `emit_many`: no call site emits more than one event
        at a time. A per-batch reservation
        (`next_seq = next_seq + :n`, spend `n-k+1..n`) is the one-line
        upgrade if a batching call site ever appears.
        """
        async with self._engine.begin() as conn:
            return await emit_in(conn, run_id, kind, payload)

    async def trim(self, keep: int = KEEP_EVENTS) -> int:
        """Keep the last `keep` events per live run; returns rows deleted.

        One set-based statement — per run a backward probe on
        `ix_run_events_run_seq`, so a run under the bound deletes nothing.
        The cost is probes, not scans, and the claim loop already pays a
        sweep per iteration.
        """
        async with self._engine.begin() as conn:
            deleted = await conn.execute(_TRIM, {"keep": keep})
        return int(deleted.rowcount)
