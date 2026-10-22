"""The Frontier port (ADR-0002, ADR-0008).

The queue lives in Postgres, and this port is the thing that makes that
decision reversible. `PostgresFrontier` (1.8) is the only adapter.

**The division of labour matters here.** The frontier persists; it does not
decide politeness. `next_eligible_at`, the backoff and the failure count are
computed by the politeness gate (1.9, spec 002 §2 and §4) and handed over in
a `Completion` so the frontier can write them in the *same transaction* that
closes the queue row. Splitting them across two transactions is the
dual-write problem ADR-0002 chose Postgres to avoid.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Protocol

from spydra.domain.enums import RenderMode
from spydra.domain.ids import DomainId, QueueItemId, RunId

# Spec 002 §3 / ADR-0004: three attempts, then the row is failed rather than
# returned for a fourth. In the port because both sides need it: the sweep
# retires a row on it, and the worker decides retry-or-fail on it.
MAX_ATTEMPTS = 3

# Every mode. The default for a claim that does not belong to a pool.
EVERY_RENDER_MODE: frozenset[RenderMode] = frozenset(RenderMode)


@unique
class QueueItemState(StrEnum):
    """`crawl_queue.state` (spec 001 §1).

    ABANDONED is not a failure: it records work a paused domain never got to,
    so a run report can show it instead of reporting a clean finish
    (ADR-0004 § Consequences).
    """

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ClaimedUrl:
    """One queue row leased to one worker."""

    id: QueueItemId
    run_id: RunId
    domain_id: DomainId
    url: str
    depth: int
    attempts: int
    locked_until: datetime


@dataclass(frozen=True, slots=True)
class Completion:
    """The outcome of a fetch, and the politeness state it produced.

    Every field is written in one transaction with the queue row (spec 002
    §2). The three domain fields are already-computed values, not
    instructions: the gate owns the jitter, the x2 backoff and the 10%
    decay, and this carries the results.
    """

    # DONE | FAILED, or PENDING to retry: spec 002 §4 retries a 5xx (and a
    # 429/503, and a request that got no response) "up to 3 attempts", and
    # the attempt was already charged by the claim, so PENDING is what makes
    # the next claim the next attempt.
    state: QueueItemState
    next_eligible_at: datetime
    crawl_delay_ms: int
    consecutive_failures: int
    # ADR-0004 pauses a domain on three CONSECUTIVE 403s, and spec 002 §4
    # increments `consecutive_failures` for 403, 429 and 503 alike — so one
    # counter cannot answer both and the refusals need their own.
    #
    # It is persisted rather than held in the worker because in-process
    # politeness state is what ADR-0003 and ADR-0026 rejected, for exactly
    # this reason: a domain that 403s twice, is restarted, and comes back
    # with a count of zero refuses for ever and never pauses. That is the
    # outcome ADR-0004 exists to prevent, and it would have passed every
    # unit test (BUILD_PLAN 1.9, found in review).
    consecutive_403s: int = 0


class Frontier(Protocol):
    async def claim(
        self, render_modes: frozenset[RenderMode] = EVERY_RENDER_MODE
    ) -> ClaimedUrl | None:
        """Lease the next eligible URL, or None if nothing is eligible.

        `render_modes` is the pool asking (spec 002 §6): the rendered pool
        claims only `rendered` domains, so a static fetch never waits behind
        a browser and the sidecar is never asked for more than its pool.

        One transaction. The per-domain concurrency limit is enforced in SQL,
        not in this process, because it has to hold across worker replicas
        and restarts (ADR-0002, ADR-0003).

        None is the ordinary case, not an error: throughput is
        `min(workers, eligible_domains)` and with two domains onboarding most
        workers are idle most of the time (spec 002 §8).
        """
        ...

    async def complete(self, item: ClaimedUrl, completion: Completion) -> None:
        """Close the row, advance the domain, decrement `in_flight`. One
        transaction."""
        ...

    async def release(self, item: ClaimedUrl) -> None:
        """Return a leased row to PENDING with no penalty.

        For `Backpressure` only (spec 002 §6): the sidecar's queue was full,
        so this is not an attempt the domain should be charged for.

        **It must still decrement `in_flight`.** Since ADR-0026 that counter
        gates claiming, so releasing without decrementing leaves the domain
        unclaimable until the lease sweep — a stall caused by our own sidecar
        being busy, which is what "try another domain" exists to avoid. No
        penalty means no `consecutive_failures`, no backoff, no attempt
        charged; it does not mean holding the gate.
        """
        ...

    async def sweep_expired_leases(self) -> int:
        """Return rows whose lease has passed to PENDING; three attempts moves
        a row to FAILED. Also reconciles the owning domain's `in_flight`,
        which spec 001 §1 calls a cache that must never be trusted without it.

        Runs at the start of every claim-loop iteration rather than as a
        janitor process (spec 002 §3). Returns the number of rows recovered.
        """
        ...

    async def abandon_domain(self, run_id: RunId, domain_id: DomainId) -> int:
        """Mark this domain's remaining PENDING rows ABANDONED.

        ADR-0004: three consecutive 403s stop the domain and the work it did
        not do is recorded, not deleted. Returns the number abandoned.
        """
        ...

    async def enqueue(
        self, run_id: RunId, domain_id: DomainId, urls: Sequence[tuple[str, int]]
    ) -> int:
        """Add (url, depth) pairs, deduplicated within the run by `url_hash`
        (spec 001 §1). Returns how many were new."""
        ...
