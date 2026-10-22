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

from spydra.domain.enums import RenderMode
from spydra.domain.ids import DomainId, QueueItemId, RunId
from spydra.domain.urls import fetchable_url, url_hash
from spydra.ports.frontier import EVERY_RENDER_MODE, MAX_ATTEMPTS, ClaimedUrl, Completion

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
_RELEASE_QUEUE = sa.text(
    """
UPDATE crawl.crawl_queue
SET state = 'pending',
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
_SWEEP = sa.text(
    """
WITH expired AS (
    SELECT id, domain_id, attempts
    FROM crawl.crawl_queue
    WHERE state = 'in_flight'
      AND locked_until IS NOT NULL
      AND locked_until < now()
    FOR UPDATE SKIP LOCKED
),
recovered AS (
    UPDATE crawl.crawl_queue q
    SET state = CASE WHEN q.attempts >= :max_attempts THEN 'failed' ELSE 'pending' END,
        locked_until = NULL
    WHERE q.id IN (SELECT id FROM expired)
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
_ENQUEUE = sa.text(
    """
INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash, depth)
SELECT :run_id, :domain_id, u.url, u.url_hash, u.depth
FROM unnest(CAST(:urls AS text[]), CAST(:hashes AS bytea[]), CAST(:depths AS int[]))
     AS u(url, url_hash, depth)
WHERE EXISTS (
          SELECT 1 FROM crawl.domains d
          WHERE d.id = :domain_id AND d.state = 'active'
          FOR SHARE
      )
  AND EXISTS (SELECT 1 FROM crawl.runs r WHERE r.id = :run_id AND r.state = 'running')
ON CONFLICT (run_id, url_hash) DO NOTHING
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
        """
        async with self._engine.begin() as conn:
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
        self, run_id: RunId, domain_id: DomainId, urls: Sequence[tuple[str, int]]
    ) -> int:
        """Add (url, depth) pairs, deduplicated within the run.

        `ON CONFLICT DO NOTHING` rather than a SELECT-then-INSERT: the unique
        index is already the constraint, and checking first is a race that
        two workers discovering the same link will lose.
        """
        if not urls:
            return 0
        async with self._engine.begin() as conn:
            result = await conn.execute(
                _ENQUEUE,
                {
                    "run_id": int(run_id),
                    "domain_id": int(domain_id),
                    "urls": [fetchable_url(url) for url, _ in urls],
                    "hashes": [url_hash(url) for url, _ in urls],
                    "depths": [depth for _, depth in urls],
                },
            )
            return len(result.fetchall())
