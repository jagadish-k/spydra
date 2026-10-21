# feat/1.8-postgres-frontier

**Task:** BUILD_PLAN `1.8` · **Spec:** `specs/002-scheduler.md` §1–3 ·
**Port:** `spydra/ports/frontier.py` (`1.2`)
**ADRs:** 0002 (postgres as queue), **0026 (the claim locks the domain row)**,
0003, 0004, 0008

**Goal.** `PostgresFrontier` — the claim query **exactly as ADR-0026
specifies it**, the lease-expiry sweep, `complete()`, `release()`,
`abandon_domain()` and `enqueue()`.

**This is the most correctness-critical slice in phase 1**, and the reason is
written down: the original query in spec 002 §1 raced **20 rounds out of 20**
on real Postgres and raised no error. So the discipline here is not "write
the SQL"— ADR-0026 already did that — it is to prove by measurement that the
guarantee holds, with two real workers on two real connections and assertions
on observed timestamps, exactly as TESTING.md §2 demands.

---

## Measured before writing anything

1. **The port is complete.** `Frontier`, `ClaimedUrl`, `Completion` and
   `QueueItemState` all exist from `1.2`. Nothing in the port needs adding,
   and `release()`'s docstring already spells out the `in_flight` trap.
2. **The schema is ready.** `domains` carries `in_flight`,
   `next_eligible_at`, `max_concurrency`, `consecutive_failures` and
   `CHECK (in_flight >= 0)`; `crawl_queue` carries `state`, `attempts`,
   `locked_until`, `depth` and `UNIQUE (run_id, url_hash)`. Both driving
   indexes exist. No migration in this slice.
3. **`conftest.py` already anticipates this task.** Its `conn` fixture
   rolls back, and its docstring says the concurrency tests must _not_ use
   it: "two workers cannot see each other's uncommitted work, so a
   rolled-back transaction would let a `SKIP LOCKED` test pass without ever
   exercising the lock". Those tests take `engine` and manage their own
   transactions.
4. **`ports/frontier.py` numbers this task `1.5` and the politeness gate
   `1.6`** — stale from the `1.5` insertion, corrected here since this slice
   owns the file.

## Decisions

- **The claim SQL is copied from ADR-0026, not re-derived.** It is three
  CTEs and the ADR says plainly that "a reviewer who does not understand why
  there are two row locks will simplify it back into the bug". So the SQL
  lives as SQL in the adapter (AGENTS.md § Conventions), with the ADR named
  at the top of it, and the two `FOR UPDATE SKIP LOCKED` clauses are
  commented with which job each does.
- **`sweep_expired_leases()` reconciles `in_flight` by recount, not by
  decrement.** Spec 001 §1 calls the counter a cache and ADR-0026 makes it
  load-bearing: an over-count stalls the domain. A sweep that decrements by
  the number of rows it recovered is still arithmetic on a value it does not
  trust, and two sweeps racing a completion can drive it negative — which
  ADR-0026 §Consequences says is the one drift direction that is actually
  _impolite_, because a negative counter lets two workers past the gate.
  Recounting from `crawl_queue` makes the cache true rather than
  less-wrong, and the `CHECK` constraint then has nothing to catch.
- **Completion, release and the sweep each do their work in one statement
  per table inside one transaction.** The port's docstring is explicit that
  splitting the queue row from the domain row across transactions is the
  dual-write problem ADR-0002 chose Postgres to avoid.
- **`enqueue()` computes `url_hash` and relies on the unique index for
  dedupe**, with `ON CONFLICT DO NOTHING` and `RETURNING` to count what was
  new. Checking first and then inserting is a race; the index is already the
  constraint, so letting it do the work is both correct and shorter.
- **No politeness arithmetic here.** `Completion` carries already-computed
  values; the jitter, the ×2 backoff and the 10% decay are `1.9`'s. A
  frontier that computed them would be the second component with an opinion
  about politeness.

## Files this slice owns

```
backend/spydra/ports/frontier.py                      (task numbers only)
backend/spydra/adapters/postgres/frontier.py          (NEW)
backend/spydra/adapters/postgres/__init__.py
backend/tests/adapters/postgres/test_frontier.py      (NEW — single-worker)
backend/tests/adapters/postgres/test_frontier_concurrency.py (NEW — two workers)
backend/tests/adapters/postgres/seed.py               (NEW — shared row builders)
backend/tests/conftest.py                             (the `clean_crawl` fixture)
docs/BUILD_PLAN.md                                    (tick 1.8 — in the PR)
```

Two additions to the plan, both declared rather than slipped in:

- **`conftest.py`** gains a `clean_crawl` fixture. The adapter takes an
  engine and opens its own transaction per call — ADR-0026 requires the claim
  to be one short transaction that is **not** held across a fetch — so its
  tests cannot run inside the rolled-back `conn` fixture: the adapter would
  commit outside it. That is the same reason `conn`'s own docstring gives for
  the concurrency tests, arrived at from the other direction.
- **`seed.py`** holds the row builders both test files need. Two copies of
  "what an eligible domain looks like" would let one suite keep passing after
  the eligibility rules changed.

**Not owned:** `spydra/domain/` (nothing needs changing),
`adapters/postgres/tables.py` (the schema is `1.1`'s and is already right),
`spydra/scheduler/` (`1.9`'s).

Two test files on purpose: one takes the rolled-back `conn` fixture, the
other must commit. Mixing them in one module is how a concurrency test ends
up silently inside a transaction that nobody else can see.

## Acceptance

From `1.8`'s "Done when" and TESTING.md §2's politeness list.

- [x] **E1** A claim returns the eligible domain's lowest-`depth` pending
      row, sets it `in_flight`, sets `locked_until`, increments `attempts`
      and increments `domains.in_flight` — all of it, in one transaction.
- [x] **E2** `claim()` returns `None` when nothing is eligible, and that is
      the ordinary case rather than an error: not active, not yet due, or
      `in_flight` already at `max_concurrency`. One test per reason, because
      a single "returns None" test passes against a query that is broken for
      a different reason than the one being exercised.
- [x] **E3** Breadth-first: `depth` orders before `id`, so listings drain
      before the products they fan out into.
- [ ] **E4 — the guarantee.** **Two real workers on two real connections**
      against one `active` domain with `max_concurrency = 1` never hold a
      claim at the same time. Asserted on **observed timestamps** of the
      claims, not on mocks, and run over enough rounds to be evidence: the
      original query failed this 20/20, so a single round proves nothing.
- [x] **E5** Two workers against **four** eligible domains reach four
      concurrent claims — the gate must not serialise work it is not meant
      to.
- [x] **E6** A killed worker's leased row returns to `pending` on sweep and
      the domain's `in_flight` is reconciled, so the domain is claimable
      again. Both halves: with ADR-0026 an unreconciled counter stalls the
      domain even though the row is back.
- [x] **E7** Three attempts moves a row to `failed` rather than returning it
      to `pending` for a fourth.
- [x] **E8** `complete()` writes the queue state and the domain's
      `next_eligible_at`, `crawl_delay_ms` and `consecutive_failures` from
      the `Completion`, and decrements `in_flight`.
- [x] **E9** `release()` returns the row to `pending` **and decrements
      `in_flight`**, with no attempt charged and no failure counted. The
      port's docstring calls out the trap: releasing without decrementing
      leaves the domain unclaimable until the sweep.
- [x] **E10** `abandon_domain()` marks the domain's remaining pending rows
      `abandoned` and leaves other domains' rows alone — the work is
      recorded, not deleted (ADR-0004).
- [x] **E11** `enqueue()` deduplicates within a run by `url_hash` and
      returns how many were new; the same URL in a _different_ run is new
      again.
- [x] **E12** `in_flight` never goes negative under a completion racing a
      sweep of the same row — the one drift direction ADR-0026 calls
      impolite, because a negative counter lets two workers past the gate.

**Every criterion mutation-tested**, and for this slice one mutation matters
more than all the others: **remove the `FOR UPDATE SKIP LOCKED` from the
`domains` CTE and E4 must go red.** That is the exact bug ADR-0026 was
written about. If E4 stays green with the domain lock removed, the test is
decoration and the guarantee is unproven.

## Mutation matrix

Nineteen mutations, each applied alone, the suite run, the file restored.
Baseline: 35 passed. **All red, none blind.**

| Mutation                                                        | Red            |
| --------------------------------------------------------------- | -------------- |
| **remove `FOR UPDATE SKIP LOCKED` from the `domains` CTE**      | **E4, E5**     |
| `in_flight + 0` — the claim does not take the gate              | E1, and 5 more |
| `ORDER BY q2.id, q2.depth` — insertion order, not breadth-first | E3, E11        |
| eligibility ignores `state`                                     | E2             |
| eligibility ignores `next_eligible_at`                          | E2             |
| eligibility ignores `max_concurrency`                           | E2, E5         |
| `locked_until = NULL` — no lease deadline                       | E1             |
| the claim does not charge the attempt                           | E1             |
| completion keeps the gate                                       | E8, **E4**     |
| completion ignores the politeness state it was handed           | E8             |
| release keeps the gate                                          | E9, E12        |
| release charges the attempt                                     | E9             |
| the sweep ignores `locked_until`                                | E6             |
| the sweep never fails a row                                     | E7             |
| the sweep does not reconcile `in_flight`                        | E6             |
| abandon reaches across domains                                  | E10            |
| abandon also takes `done` rows                                  | E10            |
| `ON CONFLICT DO NOTHING` removed                                | E11            |
| enqueue loses `depth`                                           | E11            |

### The one that matters

Removing the domain lock — the exact ADR-0026 defect — makes
`test_two_workers_never_fetch_one_domain_concurrently` fail with **8
overlapping fetch windows** against one domain at `max_concurrency = 1`.
The guarantee this system exists to keep is therefore proven by measurement
and not by reading, which is the whole reason that ADR was written.

### Two harness defects its own control found

The anti-vacuity control — "both workers must have done some work" — fired
twice, and each time the guarantee test had been **passing for the wrong
reason**:

1. **One worker was starved for all 20 rounds.** The first harness completed
   with `next_eligible_at` already in the past, so the domain was instantly
   eligible again and the worker that had just finished looped straight back
   into `claim()` with no await in between. "The two fetch windows never
   overlapped" was true because there was only ever one worker fetching.
   The fix was to give the harness the polite delay a real worker always has
   (spec 002 §2) — removing it to "keep the test focused on concurrency" had
   removed the thing that makes two workers contend at all.
2. **A fixed iteration budget stopped both workers with the queue half
   drained.** With a polite delay between rounds, both burned their budget on
   missed polls. Now the loop is driven by the shared log reaching the target,
   with a deadline as the backstop so a genuine stall fails rather than hangs.

Without that control, both versions would have shipped green.

### One assertion deliberately not made

Whether two _simultaneous_ claims on one domain both succeed is **not
deterministic** — `asyncio.gather` starts both coroutines but the first can
finish its whole transaction before the second reaches the database.
Measured flaky across three consecutive runs. So the control asserts the two
invariants instead: never more than `max_concurrency`, and `max_concurrency`
is reachable.

## Handoff log

- **planner** — contract above. The SQL is ADR-0026's, copied rather than
  re-derived. The one mutation this slice stands or falls on is named in the
  acceptance section.
- **backend** — the claim is ADR-0026's SQL with the two locks commented for
  which job each does. Three decisions beyond it:
  **(a)** the sweep reconciles `in_flight` by **recount**, not by decrementing
  what it recovered. Spec 001 §1 calls the counter a cache, and subtracting a
  number from a value you do not trust leaves a differently-untrusted value;
  two sweeps racing a completion can drive it negative, which ADR-0026
  §Consequences says is the one drift direction that is actually _impolite_.
  A recount makes the cache true, and the `CHECK` then has nothing to catch.
  **(b)** `GREATEST(… - 1, 0)` on every decrement, for the same reason.
  **(c)** `release()` gives the **attempt** back as well as the gate. Spec 002
  §6's "no penalty" has to mean no attempt charged, or three busy moments at
  our own sidecar would retire a healthy row.
- **test** — 35 tests in two files, split because the concurrency tests must
  commit and the rest should not. Two guards are unusual and earn their place:
  one asserts the **claim SQL still contains two `FOR UPDATE SKIP LOCKED`
  clauses** and names ADR-0026 in its failure message, because the bug is
  silent and the real proof is slow enough that someone under pressure may
  narrow it; the other asserts **no politeness arithmetic appears in this
  adapter's SQL** — no `random(`, no `* 2`, no decay constants — because the
  port's docstring makes that division of labour the thing that keeps two
  components from disagreeing about when a domain may be fetched.
- **test (mutation)** — the matrix above, and the two harness defects its own
  control caught.
- **integrator** — `make check` green.

## Open questions

1. **ADR-0026 addendum: `SKIP LOCKED` on `domains` costs `max_concurrency`
   its simultaneity.** Measured. When two claim transactions genuinely
   overlap on one domain, the second finds the domain row locked and **skips
   a domain it was entitled to use** — capacity was 2. ADR-0026 justifies
   `SKIP LOCKED` over plain `FOR UPDATE` on the grounds that "blocking would
   make a worker wait for a domain it is not allowed to fetch from anyway",
   which is true at `max_concurrency = 1` and not above it.
   It costs correctness nothing and throughput almost nothing — the claim
   transaction is microseconds, the loser wins on its next attempt, and
   erring toward _fewer_ concurrent fetches is the safe direction. Recorded
   in a test with that reasoning rather than treated as a defect.
   **For the human:** worth an addendum to ADR-0026 so the next reader does
   not discover it from a flaky test.
2. **TESTING.md §2 says "Two workers, four domains → four concurrent", which
   cannot be literally true** — two workers cannot hold four claims. The
   intent is clearly that the gate must not serialise across domains, so the
   test uses four claimers against four domains. **For the human:** the
   wording should say four.
3. **Nothing yet calls `sweep_expired_leases()` on a schedule.** Spec 002 §3
   puts it at the start of every claim-loop iteration and ADR-0026 makes it
   load-bearing rather than hygiene, but the claim loop is `1.13`. Until
   then an over-counted `in_flight` is only cleared by a test. Named here so
   `1.13` cannot forget it.
