# 0026 — The claim query locks the domain row, not just the queue row

**Status:** Accepted · 2026-10-17
**Relates to:** [ADR-0002](0002-postgres-as-queue.md) (postgres as the queue),
[ADR-0003](0003-three-pools-one-gate.md) (three pools, one gate),
[ADR-0004](0004-stop-on-block.md) (a block stops the crawler)
**Amends:** `docs/specs/002-scheduler.md` §1

## Context

ADR-0003 puts the per-domain concurrency limit in the database rather than in
process memory, so it holds across worker replicas and restarts. ADR-0002
makes the claim a single `SELECT … FOR UPDATE SKIP LOCKED` inside the
transaction that writes the result. Spec 002 §9's first acceptance test —
"two workers against one active domain never fetch concurrently" — is the
test that proves the politeness guarantee this system exists to keep.

The query as spec 002 §1 originally wrote it does not deliver it. Found while
planning phase 1, before `PostgresFrontier` was written:

```sql
WITH eligible AS (
    SELECT d.id FROM domains d
    WHERE d.state = 'active' AND d.next_eligible_at <= now()
      AND d.in_flight < d.max_concurrency
    ORDER BY d.next_eligible_at LIMIT 1
)
UPDATE crawl_queue q SET state = 'in_flight', …
WHERE q.id = (SELECT q2.id FROM crawl_queue q2 JOIN eligible e ON e.id = q2.domain_id
              WHERE q2.state = 'pending' ORDER BY q2.depth, q2.id
              FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING q.*;
```

Two defects:

1. **Nothing locks the domain row, and the query does not complain.** The
   `FOR UPDATE SKIP LOCKED` sits in a subquery selecting
   `FROM crawl_queue q2 JOIN eligible e`, so it locks `crawl_queue` and not
   the eligibility decision. Two workers running the claim concurrently both
   read the *same* single eligible domain; neither has committed its
   `in_flight` increment, so both see `in_flight < max_concurrency`.
   `SKIP LOCKED` then hands them two *different* queue rows **of that one
   domain**. With `max_concurrency = 1` that is two simultaneous connections
   to one host: the exact failure the guarantee forbids, arrived at through
   the mechanism meant to prevent it.
2. **The `in_flight` increment is missing from the statement**, though §1's
   prose says it happens "in the same transaction".

`next_eligible_at` does not save it. §2 advances that only *after* the fetch,
so during the window both workers see the same value. `in_flight` is the only
guard, and it is invisible to a concurrent reader until commit.

**A third defect was suspected and is not real.** The planning note that led
to this ADR claimed Postgres rejects `FOR UPDATE` applied to a `WITH`
reference outright, so the query would error rather than race. Measured, it
does not: Postgres accepts the statement and quietly locks only
`crawl_queue`. That is worse than an error — an error is a failed `make
migrate`, whereas this is a politeness guarantee that reports success.
Recorded because the reason to prefer the measurement over the reasoning is
the point of the evidence below.

## Evidence

Both queries were run against real Postgres, two separate connections, one
`active` domain with `max_concurrency = 1`, six pending queue rows, both
workers released into the claim together and each holding its transaction
open for 250 ms afterwards to stand in for a fetch. Twenty rounds each, the
tables truncated between rounds:

| Query | Rounds where **both** workers claimed | Rounds where the query errored |
| --- | --- | --- |
| §1 as originally written | **20 / 20** | 0 |
| This ADR | **0 / 20** | 0 |

The race is not a narrow window to be argued about: under this timing the
original query fails every single time, silently. Measured on PostgreSQL
16.15 rather than the project's 18 — row locking and `SKIP LOCKED` have not
changed between them, but the number is from 16 and `make test-api` on 18 is
what settles it.

## Decision

**The claim locks the domain row it selects, with `FOR UPDATE SKIP LOCKED`,
and increments `in_flight` in the same statement.** A domain under
consideration by one worker is skipped by another rather than read
optimistically.

```sql
WITH eligible AS (
    SELECT d.id
    FROM crawl.domains d
    WHERE d.state = 'active'
      AND d.next_eligible_at <= now()
      AND d.in_flight < d.max_concurrency
    ORDER BY d.next_eligible_at
    FOR UPDATE SKIP LOCKED          -- on domains: the gate
    LIMIT 1
),
claimed AS (
    UPDATE crawl.crawl_queue q
    SET state = 'in_flight',
        locked_until = now() + interval '120 seconds',
        attempts = attempts + 1
    WHERE q.id = (
        SELECT q2.id
        FROM crawl.crawl_queue q2
        WHERE q2.domain_id = (SELECT id FROM eligible)
          AND q2.state = 'pending'
        ORDER BY q2.depth, q2.id     -- breadth-first: listings before products
        FOR UPDATE SKIP LOCKED       -- on crawl_queue: the dequeue
        LIMIT 1
    )
    RETURNING q.*
)
UPDATE crawl.domains d
SET in_flight = d.in_flight + 1
WHERE d.id = (SELECT domain_id FROM claimed)
RETURNING (SELECT row_to_json(c) FROM claimed c);
```

Two locks, two jobs, and they are not interchangeable:

- **`FOR UPDATE SKIP LOCKED` on `domains`** is the politeness gate. It
  serialises the *eligibility decision*, which is the thing that was racing.
- **`FOR UPDATE SKIP LOCKED` on `crawl_queue`** is the dequeue, and is what
  ADR-0002 was always about: two workers never take the same URL.

`SKIP LOCKED` on the domain and not plain `FOR UPDATE`: blocking would make
a worker wait for a domain it is not allowed to fetch from anyway, when
another domain may be eligible. Skipping lets it move on, which is the same
reason ADR-0002 chose `SKIP LOCKED` for the queue.

The domain lock is held for the duration of the claim transaction only —
microseconds — and **not** for the fetch. The fetch is gated by `in_flight`
and `next_eligible_at`, which are committed state. A lock held across a
two-second polite delay, or a five-second render, would idle a connection for
the whole crawl.

### Consequence for the lease sweep

`in_flight` is now incremented by the claim and decremented by completion or
by the lease sweep, and the sweep remains the only thing that makes it true
(spec 001 §1 calls it a cache, not a fact). That does not change. What does
change is that an over-counted `in_flight` now **blocks** claiming for that
domain rather than merely mis-reporting, so the sweep running at the start of
every claim-loop iteration (spec 002 §3) moves from hygiene to load-bearing.

## Consequences

- **Spec 002 §9's first acceptance test can now pass**, and must be written
  the way TESTING.md §2 demands: two real workers, two real connections,
  asserting on observed fetch timestamps. Against the original SQL it would
  have failed — or errored on the CTE lock — and the temptation at that point
  is to weaken the test rather than the query.
- **Throughput is unchanged.** It was already `min(workers, eligible_domains)`
  (spec 002 §8); the domain lock makes that ceiling real instead of
  approximate.
- **One statement, one transaction**, so ADR-0002's atomicity argument holds:
  a crash rolls the whole claim back and the row returns to `pending` when its
  lease expires.
- **Cost: the claim is now three CTEs reading as one statement, and it is the
  hardest SQL in the project.** It is deliberately written as SQL in the
  Postgres adapter rather than assembled by an ORM (AGENTS.md § Conventions),
  with this ADR as the explanation. A reviewer who does not understand why
  there are two row locks will simplify it back into the bug.
- **Cost: `max_concurrency > 1` is now genuinely limited by the counter**, and
  the counter is a cache. A domain whose `in_flight` is stuck high fetches
  nothing until the sweep reconciles it — a stall rather than a rudeness,
  which is the correct direction to fail, but it is a real failure mode that
  did not exist when the counter was only advisory.

## Alternatives considered

**A `CHECK (in_flight <= max_concurrency)` constraint.** Rejected as the
primary mechanism: it turns the race into a constraint violation the worker
must catch and retry, so every claim grows an error path, and a failed claim
is indistinguishable from an empty queue. Worth adding later as a backstop
that would make a regression loud; not worth making the gate.

**An advisory lock per domain (`pg_try_advisory_xact_lock`).** Rejected.
It works, and it puts the politeness guarantee somewhere `SELECT`-ing the
tables cannot see it — the lock would exist only in the adapter's code, where
spec 002 §9's test cannot assert on it and a future reader has no reason to
look.

**Serialisable isolation for the claim transaction.** Rejected. It would
detect the conflict, at the price of serialisation failures to retry under
exactly the load where claiming matters, and it would make the guarantee a
property of a session setting rather than of the query. `SKIP LOCKED` already
expresses the intent: skip what someone else is handling.

**Keeping the limit in process.** Rejected by ADR-0003: the limit has to hold
across worker replicas and restarts, and in-process state does neither.
