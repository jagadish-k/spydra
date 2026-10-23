"""`Frontier` over Postgres (BUILD_PLAN 1.8).

The queue is a table, not a broker (ADR-0002), and this is the adapter that
makes that decision reversible — everything above it talks to the port.

**Read [ADR-0026](../../../../docs/adr/0026-claim-locks-the-domain-row.md)
before touching the claim.** The query below has two `FOR UPDATE SKIP
LOCKED` clauses doing two different jobs, and the version with only the
second one — which is what spec 002 §1 originally said — let two workers
fetch the same host concurrently in **twenty rounds out of twenty** on real
Postgres, with no error raised. That is the politeness guarantee this system
exists to keep, failing silently through the mechanism meant to prevent it.
A reviewer who does not see why there are two locks will simplify it back.

The SQL is written as SQL rather than assembled by an ORM, deliberately
(AGENTS.md § Conventions): the query *is* the guarantee, and a query you
cannot read in one piece is one nobody will check against the ADR.

**No politeness arithmetic lives here.** `Completion` carries values the
politeness gate (`1.9`) already computed — the jitter, the ×2 backoff, the
10% decay. A frontier that computed them would be a second component with an
opinion about politeness, which is how two components disagree about when a
domain may be fetched.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.runs import _STATS
from spydra.domain.enums import RenderMode
from spydra.domain.ids import DomainId, QueueItemId, RunId
from spydra.domain.urls import fetchable_url, url_hash
from spydra.ports.frontier import (
    EVERY_RENDER_MODE,
    MAX_ATTEMPTS,
    ClaimedUrl,
    Completion,
    Enqueued,
    RunHalt,
)

__all__ = ["LEASE_SECONDS", "MAX_ATTEMPTS", "PostgresFrontier", "url_hash"]

# Spec 002 §1. A lease long enough for a slow render (spec 012 §2 allows 30 s)
# plus the politeness delay in front of it, short enough that a killed worker
# does not strand a row for minutes.
LEASE_SECONDS = 120


# ---------------------------------------------------------------------------
# The claim. ADR-0026, verbatim in structure.
# ---------------------------------------------------------------------------

_CLAIM = sa.text(
    """
WITH eligible AS (
    SELECT d.id
    FROM crawl.domains d
    WHERE d.state = 'active'
      AND d.next_eligible_at <= now()
      AND d.in_flight < d.max_concurrency
      AND d.render_mode = ANY(CAST(:render_modes AS text[]))
      -- ADR-0034: only a domain with work. Without this, a domain whose
      -- queue has drained is never fetched again, so its next_eligible_at
      -- never advances, it stays the MOST eligible domain for good, and
      -- every other domain's claim comes back empty for ever.
      AND EXISTS (
          SELECT 1 FROM crawl.crawl_queue q0
          WHERE q0.domain_id = d.id AND q0.state = 'pending'
          -- ADR-0041: a pending row is work only while its run is
          -- running. One predicate buys both states: a terminal run's
          -- rows stop being claimable (the domain is skipped entirely
          -- rather than locked-then-empty), and a paused run's stop
          -- being claimable without being touched — pause is resumable,
          -- and that distinction is why both states exist. Cost: one PK
          -- probe per candidate inside an EXISTS that already runs per
          -- eligible domain; the guarded enqueue has carried the same
          -- run-state EXISTS since 2.3.
          AND EXISTS (SELECT 1 FROM crawl.runs r
                      WHERE r.id = q0.run_id AND r.state = 'running')
      )
    ORDER BY d.next_eligible_at
    FOR UPDATE SKIP LOCKED          -- on domains: THE POLITENESS GATE.
                                    -- Serialises the eligibility DECISION.
                                    -- Without this, two workers both read the
                                    -- same eligible domain, neither has
                                    -- committed its in_flight increment, and
                                    -- SKIP LOCKED below hands them two
                                    -- different rows OF THAT ONE DOMAIN.
                                    -- ADR-0026: 20 rounds out of 20.
    LIMIT 1
),
claimed AS (
    UPDATE crawl.crawl_queue q
    SET state = 'in_flight',
        locked_until = now() + (:lease_seconds * interval '1 second'),
        attempts = attempts + 1
    WHERE q.id = (
        SELECT q2.id
        FROM crawl.crawl_queue q2
        WHERE q2.domain_id = (SELECT id FROM eligible)
          AND q2.state = 'pending'
        ORDER BY q2.depth, q2.id     -- breadth-first: listings fan out into
                                     -- products, so draining them early keeps
                                     -- the frontier full (spec 002 §1)
        FOR UPDATE SKIP LOCKED       -- on crawl_queue: THE DEQUEUE.
                                     -- Two workers never take the same URL.
        LIMIT 1
    )
    RETURNING q.*
)
UPDATE crawl.domains d
SET in_flight = d.in_flight + 1
WHERE d.id = (SELECT domain_id FROM claimed)
RETURNING (SELECT row_to_json(c) FROM claimed c) AS claimed
"""
)

# Completion: the queue row and the domain row, one transaction (spec 002 §2).
#
# **Fenced on the lease.** The row is closed only if it is still `in_flight`
# under the `locked_until` this claim set. Without that, two things closed a
# row twice. A worker whose crawl raised after `complete` had committed went
# on to `abort`, which reopened a 403 for retry (a retry through a block,
# AGENTS.md rule 8). And a lease that expired mid-crawl had its row swept and
# re-claimed, after which the first owner closed the second owner's lease.
# Each extra close also took `in_flight` down again.
_COMPLETE_QUEUE = sa.text(
    """
UPDATE crawl.crawl_queue
SET state = :state, locked_until = NULL
WHERE id = :id AND state = 'in_flight' AND locked_until = :lease
RETURNING id
"""
)

# A completion whose lease was lost still reports a request the host really
# received, so the gate is pushed forward, never back. Nothing else is
# touched: the counters and `in_flight` belong to whoever holds the row now.
_STALE_COMPLETION = sa.text(
    """
UPDATE crawl.domains
SET next_eligible_at = GREATEST(next_eligible_at, :next_eligible_at)
WHERE id = :domain_id
"""
)

_COMPLETE_DOMAIN = sa.text(
    """
UPDATE crawl.domains
SET next_eligible_at = :next_eligible_at,
    crawl_delay_ms = :crawl_delay_ms,
    consecutive_failures = :consecutive_failures,
    -- ADR-0004's pause counts CONSECUTIVE 403s, which spec 002 §4's shared
    -- failure counter cannot express. Written here because the gate computes
    -- it and nothing else may: held in worker memory it resets on restart
    -- and the domain refuses for ever without ever pausing.
    consecutive_403s = :consecutive_403s,
    -- GREATEST, not `- 1`: the counter is a cache (spec 001 §1) and a
    -- completion racing the sweep of the same row would otherwise drive it
    -- negative. ADR-0026 §Consequences: negative is the one drift direction
    -- that is actually impolite, because `in_flight < max_concurrency` then
    -- passes more often than it should and two workers fetch one host.
    in_flight = GREATEST(in_flight - 1, 0)
WHERE id = :domain_id
"""
)

# Release: PENDING again, no penalty — but the gate must be given back
# (spec 002 §6, and the port's own docstring).
#
# **The run row is share-locked BEFORE the routing statement** (ADR-0041).
# A stop or cap-halt committing between this statement's read and the
# release's commit would leave the row `pending` on a terminal run —
# unclaimable (the claim fence holds) but permanently unreported. `FOR
# SHARE` is the 2.3/`_ENQUEUE` pattern turned on the run row: the terminal
# writers take it `FOR UPDATE` before their abandon, so either they commit
# first and this statement reads the terminal state, or they wait and
# their abandon sees the row this release returns to `pending`.
_LOCK_RUN_FOR_RELEASE = sa.text(
    """
SELECT id FROM crawl.runs WHERE id = :run_id FOR SHARE
"""
)

_RELEASE_QUEUE = sa.text(
    """
UPDATE crawl.crawl_queue
SET state = CASE WHEN (SELECT r.state FROM crawl.runs r
                       WHERE r.id = crawl_queue.run_id)
                    IN ('completed', 'stopped', 'failed')
               -- ADR-0041: claimable ⇔ run running. A row released after
               -- its run went terminal (SIGTERM, backpressure, a claim
               -- that raced the signal) must not land `pending`: the
               -- claim fence would hold it unclaimable for ever,
               -- unreported — a silent hole in the stats written at the
               -- terminal transition. A paused run's row still returns
               -- to `pending`: pause keeps every row, it freezes dequeue.
               THEN 'abandoned' ELSE 'pending' END,
    locked_until = NULL,
    -- The attempt is given back too. Spec 002 §6's "no penalty" means no
    -- consecutive_failures, no backoff AND no attempt charged — otherwise
    -- three busy moments at our own sidecar would retire a healthy row.
    attempts = GREATEST(attempts - 1, 0)
WHERE id = :id AND state = 'in_flight' AND locked_until = :lease
RETURNING id
"""
)

_RELEASE_DOMAIN = sa.text(
    """
UPDATE crawl.domains
SET in_flight = GREATEST(in_flight - 1, 0)
WHERE id = :domain_id
"""
)

# The sweep. Spec 002 §3, and load-bearing since ADR-0026.
#
# The run row is share-locked **in the statement** (`FOR SHARE OF r`),
# the `_ENQUEUE` pattern turned on the run row (ADR-0041): the routing
# CASE's read of `r.state` and the row's fate are decided atomically under
# a lock the terminal writers (`stop_run`, `halt_run`) take exclusively
# before their abandon — so a swept row of a run that stops mid-sweep
# routes `abandoned`, never `pending`-on-terminal. In the statement, not
# a preceding one: a lock taken by an earlier statement of this
# transaction holds a *different* snapshot's candidate set, and a row
# expiring between the two would route unlocked.
_SWEEP = sa.text(
    """
WITH expired AS (
    SELECT q.id, q.domain_id, q.attempts, r.state AS run_state
    FROM crawl.crawl_queue q
    JOIN crawl.runs r ON r.id = q.run_id
    WHERE q.state = 'in_flight'
      AND q.locked_until IS NOT NULL
      AND q.locked_until < now()
    -- OF q: lock queue rows exactly as before. No SKIP LOCKED on r: a
    -- terminal writer holding the run row exclusively is exactly what
    -- this sweep must wait for, and it holds it only for microseconds.
    FOR UPDATE OF q SKIP LOCKED FOR SHARE OF r
),
recovered AS (
    UPDATE crawl.crawl_queue q
    SET state = CASE
            WHEN e.attempts >= :max_attempts THEN 'failed'
            -- ADR-0041: claimable ⇔ run running. A swept row of a
            -- terminal run must not go back to `pending` — unclaimable
            -- (the claim fence holds) but unreported, a silent hole in
            -- the stats written at the terminal transition. `attempts`
            -- still wins first: an exhausted row failed, whatever its
            -- run did.
            WHEN e.run_state IN ('completed', 'stopped', 'failed') THEN 'abandoned'
            ELSE 'pending'
        END,
        locked_until = NULL
    FROM expired e
    WHERE q.id = e.id
    RETURNING q.id, q.domain_id
)
SELECT count(*) AS recovered FROM recovered
"""
)

# Reconcile by RECOUNT, not by decrement. Spec 001 §1 calls in_flight a cache;
# subtracting a number from a value you do not trust leaves you with a
# different untrusted value, and two sweeps racing a completion can drive it
# negative. Counting the rows that are actually in flight makes the cache
# TRUE, which is what ADR-0026 needs from it now that it gates claiming.
_RECONCILE_IN_FLIGHT = sa.text(
    """
UPDATE crawl.domains d
SET in_flight = sub.actual
FROM (
    SELECT d2.id,
           (SELECT count(*)
            FROM crawl.crawl_queue q
            WHERE q.domain_id = d2.id AND q.state = 'in_flight') AS actual
    FROM crawl.domains d2
) AS sub
WHERE d.id = sub.id AND d.in_flight <> sub.actual
"""
)

_ABANDON = sa.text(
    """
UPDATE crawl.crawl_queue
SET state = 'abandoned'
WHERE run_id = :run_id AND domain_id = :domain_id AND state = 'pending'
"""
)

# One statement per page, and only into a live run on an active domain.
#
# **The guard is in the INSERT, under a share lock on the domain row.** A
# check made first and an insert made after is a race: another worker can
# halt the domain (`BREAK`, a 403 pause) and abandon its pending rows in
# between, and rows inserted after that are claimed by nobody, so the run
# never drains (2.3 review finding 1, reproduced). `FOR SHARE` makes a
# concurrent halt's `UPDATE domains` wait for this insert to commit, so its
# abandon sees these rows; an insert that waited on a halt re-reads the state
# and inserts nothing. The run must still be `running`: a worker whose lease
# was lost can otherwise add work to a run the sweep already finished.
#
# `unnest` makes it one round trip whatever the page links to: a mega-menu
# page re-sends hundreds of links, almost all of them conflicts.
#
# The cap (ADR-0040) joins those guards. `queued` counts the run's rows for
# the domain in every state — abandoned and failed rows are work discovery
# produced — under the same statement snapshot; while the count is below
# `cap` the whole batch inserts, at or past it nothing does. What comes
# back with the yield is `capped`: the count after this batch has reached
# the cap, the breach signal the caller halts the run on. The count never
# comes back down within a run, so refusal after a breach is self-healing —
# no flag to keep true.
_ENQUEUE = sa.text(
    """
WITH queued AS (
    SELECT count(*) AS n
    FROM crawl.crawl_queue
    WHERE run_id = :run_id AND domain_id = :domain_id
),
inserted AS (
    INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash, depth)
    SELECT :run_id, :domain_id, u.url, u.url_hash, u.depth
    FROM unnest(CAST(:urls AS text[]), CAST(:hashes AS bytea[]), CAST(:depths AS int[]))
         AS u(url, url_hash, depth)
    WHERE EXISTS (
              SELECT 1 FROM crawl.domains d
              WHERE d.id = :domain_id AND d.state = 'active'
              FOR SHARE
          )
      -- ADR-0041: widened from `= 'running'` to admit `paused`. Pause
      -- freezes dequeue, not discovery: a paused run's in-flight tail
      -- still crawls, and dropping its links would make resume produce a
      -- silently incomplete crawl — the worst failure mode a pause can
      -- have, and it leaves no trace.
      AND EXISTS (SELECT 1 FROM crawl.runs r
                  WHERE r.id = :run_id AND r.state IN ('running', 'paused'))
      AND (SELECT n FROM queued) < :cap
    ON CONFLICT (run_id, url_hash) DO NOTHING
    RETURNING id
)
SELECT (SELECT count(*) FROM inserted) AS added,
       (SELECT n FROM queued) + (SELECT count(*) FROM inserted) >= :cap AS capped
"""
)

# Same serialisation for the cap halt (ADR-0041): the `failed` edge has
# the same abandon-then-transition shape as stop, so the routing writers'
# `FOR SHARE` needs the same exclusive counterpoint or a release racing a
# breach-halt lands `pending` on a failed run.
_LOCK_RUN_FOR_HALT = sa.text(
    """
SELECT id FROM crawl.runs WHERE id = :run_id AND state = 'running' FOR UPDATE
"""
)


# ADR-0040's recording. `state = 'running'` makes it first-signaller-wins:
# a later in-flight re-signal — or a concurrent clean finish that got
# there first — matches no row, so the run is failed exactly once, only by
# a caller that found it still running.
#
# `_STATS` is the shape every finish writes (runs.py), shared rather than
# duplicated — and this UPDATE is deliberately the SECOND statement of the
# halt transaction, after the abandon. A single data-modifying CTE cannot
# see a sibling CTE's writes (PostgreSQL runs them on one snapshot), so a
# stats subquery beside the abandon CTE would count this breach's rows as
# still `pending` and write `pages_abandoned = 0` — the clean finish
# ADR-0040 forbids. Within one transaction the later statement sees the
# earlier's writes; the transaction, not the statement count, is what
# keeps the halt atomic.
_HALT_RUN = sa.text(
    f"""
UPDATE crawl.runs
SET state = 'failed', stop_reason = :reason, finished_at = now(),
    stats = {_STATS}
WHERE id = :run_id AND state = 'running'
RETURNING id
"""
)


class PostgresFrontier:
    """`Frontier` over the `crawl` schema.

    Takes an engine rather than a connection: `claim()` and `complete()` are
    each one transaction, and holding one open across a fetch is exactly what
    ADR-0026 §Consequences says a crawler cannot do.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim(
        self, render_modes: frozenset[RenderMode] = EVERY_RENDER_MODE
    ) -> ClaimedUrl | None:
        """Lease the next eligible URL, or None.

        None is the ordinary case, not an error: throughput is
        `min(workers, eligible_domains)` and with two domains onboarding most
        workers are idle most of the time (spec 002 §8).
        """
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    _CLAIM,
                    {
                        "lease_seconds": LEASE_SECONDS,
                        # Sorted so the bound value is deterministic.
                        "render_modes": sorted(m.value for m in render_modes),
                    },
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return ClaimedUrl(
            id=QueueItemId(row["id"]),
            run_id=RunId(row["run_id"]),
            domain_id=DomainId(row["domain_id"]),
            url=row["url"],
            depth=row["depth"],
            attempts=row["attempts"],
            # `row_to_json` renders it as text, so it arrived as a `str` that
            # the annotation called a `datetime`. Harmless until 1.13 sent it
            # back as the lease fence, where asyncpg refused it.
            locked_until=datetime.fromisoformat(row["locked_until"]),
        )

    async def complete(self, item: ClaimedUrl, completion: Completion) -> bool:
        """Close the row and advance the domain. One transaction.

        Both statements or neither: the port's docstring is explicit that
        splitting them is the dual-write problem ADR-0002 chose Postgres to
        avoid, and a completion that closed the row without giving the gate
        back would stall the domain until the sweep.

        `False` when this lease no longer holds the row (see `_COMPLETE_QUEUE`).
        """
        async with self._engine.begin() as conn:
            closed = (
                await conn.execute(
                    _COMPLETE_QUEUE,
                    {"id": int(item.id), "state": completion.state, "lease": item.locked_until},
                )
            ).scalar_one_or_none()
            if closed is None:
                await conn.execute(
                    _STALE_COMPLETION,
                    {
                        "domain_id": int(item.domain_id),
                        "next_eligible_at": completion.next_eligible_at,
                    },
                )
                return False
            await conn.execute(
                _COMPLETE_DOMAIN,
                {
                    "domain_id": int(item.domain_id),
                    "next_eligible_at": completion.next_eligible_at,
                    "crawl_delay_ms": completion.crawl_delay_ms,
                    "consecutive_failures": completion.consecutive_failures,
                    "consecutive_403s": completion.consecutive_403s,
                },
            )
        return True

    async def release(self, item: ClaimedUrl) -> bool:
        """Back to PENDING with no penalty — and the gate given back.

        Fenced like `complete`: a row this lease already closed, or lost, is
        left alone, so a release on shutdown cannot reopen a finished page.

        The run row is share-locked first (see `_LOCK_RUN_FOR_RELEASE`) so
        the pending-vs-abandoned routing cannot race a terminal
        transition (ADR-0041).
        """
        async with self._engine.begin() as conn:
            await conn.execute(_LOCK_RUN_FOR_RELEASE, {"run_id": int(item.run_id)})
            released = (
                await conn.execute(_RELEASE_QUEUE, {"id": int(item.id), "lease": item.locked_until})
            ).scalar_one_or_none()
            if released is None:
                return False
            await conn.execute(_RELEASE_DOMAIN, {"domain_id": int(item.domain_id)})
        return True

    async def sweep_expired_leases(self) -> int:
        """Recover expired leases and make `in_flight` true again.

        Two statements, one transaction, and the second one is the half that
        is easy to leave out: with ADR-0026 an `in_flight` left high by a
        dead worker stops that domain being claimed **at all**, so a sweep
        that returned the row without reconciling the counter would fix the
        visible symptom and leave the stall in place.
        """
        async with self._engine.begin() as conn:
            recovered = (await conn.execute(_SWEEP, {"max_attempts": MAX_ATTEMPTS})).scalar_one()
            await conn.execute(_RECONCILE_IN_FLIGHT)
        return int(recovered)

    async def abandon_domain(self, run_id: RunId, domain_id: DomainId) -> int:
        """Record the work a paused domain never got to (ADR-0004).

        `abandoned`, not deleted: the run report shows what was not done
        instead of reporting a clean finish.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                _ABANDON, {"run_id": int(run_id), "domain_id": int(domain_id)}
            )
        return int(result.rowcount)

    async def enqueue(
        self, run_id: RunId, domain_id: DomainId, urls: Sequence[tuple[str, int]], *, cap: int
    ) -> Enqueued:
        """Add (url, depth) pairs, deduplicated within the run, under the
        domain's per-run cap (ADR-0040).

        `ON CONFLICT DO NOTHING` rather than a SELECT-then-INSERT: the
        unique index is already the constraint, and checking first is a
        race that two workers discovering the same link will lose.
        """
        if not urls:
            return Enqueued(added=0, capped=False)
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    _ENQUEUE,
                    {
                        "run_id": int(run_id),
                        "domain_id": int(domain_id),
                        "urls": [fetchable_url(url) for url, _ in urls],
                        "hashes": [url_hash(url) for url, _ in urls],
                        "depths": [depth for _, depth in urls],
                        "cap": cap,
                    },
                )
            ).one()
        return Enqueued(added=int(row.added), capped=bool(row.capped))

    async def halt_run(self, run_id: RunId, domain_id: DomainId, reason: str) -> RunHalt:
        """Fail the run with `reason` and abandon its pending rows for the
        domain, in one transaction (ADR-0040).

        The abandon runs first so the stats written with the failure count
        the rows it abandoned (see `_HALT_RUN`). The domain row is never
        touched: it stays `active`, and the next run's count starts at
        zero, below any cap. The run row is locked `FOR UPDATE` before the
        abandon (see `_LOCK_RUN_FOR_HALT`) so the release/sweep routing
        cannot return a row to `pending` on this transition (ADR-0041).
        """
        async with self._engine.begin() as conn:
            await conn.execute(_LOCK_RUN_FOR_HALT, {"run_id": int(run_id)})
            abandoned = await conn.execute(
                _ABANDON, {"run_id": int(run_id), "domain_id": int(domain_id)}
            )
            halted = (
                await conn.execute(_HALT_RUN, {"run_id": int(run_id), "reason": reason})
            ).scalar_one_or_none()
        return RunHalt(abandoned=int(abandoned.rowcount), transitioned=halted is not None)
