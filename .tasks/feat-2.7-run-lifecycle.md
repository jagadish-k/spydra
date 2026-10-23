# feat/2.7-run-lifecycle

**Task:** BUILD_PLAN 2.7 · **Spec:** specs/001-domain-model.md §1 (runs DDL,
`run_state`), §2 (lifecycle — gains the run transition table this slice pins),
specs/009-observability.md §5 (stats on completion, stop and failure alike)
**ADRs that constrain this:** 0004 (abandon, never delete), 0026 (claim shape —
read before touching `_CLAIM`), 0034 (claim only a domain with work), 0040
(the first non-completed terminal transition; `stop_reason` precedent, the
`_STATS` reuse, the two-statement/one-transaction ordering), **0041 (new —
written by backend this slice, content pinned in "Decided (planner)" below)**
**Stacked on:** `feat/2.6-mega-menu-guard` (PR pending)

## Decided (user)

- **An operator entry point ships NOW, not in 3.4**: the adapter plus a `make`
  target. 3.4's API later wraps the same call.
- **On stop: in-flight rows finish their fetch and close normally; pending
  rows are abandoned and reported.** The run reports the work it did not do.

## Decided (planner)

The design core. The implementer and test-writer have these words and nothing
else; where a mechanism was chosen, the losers are named so review can check
the reasoning rather than re-derive it.

### 1. The claim/run-state fence — one predicate, in the claim

`_CLAIM`'s eligible CTE already carries ADR-0034's work-check EXISTS. The run
fence goes **inside that EXISTS**: a pending row only counts as work if its
run is `state = 'running'`:

```sql
AND EXISTS (SELECT 1 FROM crawl.runs r
            WHERE r.id = q0.run_id AND r.state = 'running')
```

One predicate buys both states: a **stopped/failed/completed** run's rows stop
being claimable (terminal, and the domain is skipped entirely rather than
locked-then-empty), and a **paused** run's rows stop being claimable without
being touched (pause is resumable; that distinction is the whole point of both
states existing). Cost against ADR-0026: one PK probe per pending-row candidate
inside an EXISTS that already runs per eligible domain; the guarded enqueue
(`_ENQUEUE`) has carried an identical run-state EXISTS since 2.3 — the
precedent is in the file already.

**The same predicate at the other two places a row can leave `in_flight` back
to claimable:**

- `_SWEEP`: the recovery CASE gains a branch — `attempts >= max` still wins
  (an exhausted row failed; that is accurate), then a row whose run is
  terminal (`completed|stopped|failed`) goes to `abandoned`, else `pending`.
  The expired CTE needs the run's state, one lookup per expired row.
- `_RELEASE_QUEUE` (backpressure, SIGTERM, claim-raced-signal): released row
  goes to `abandoned` if its run is terminal, else `pending`.

This keeps the invariant **a terminal run holds no pending rows** true at the
write, so the stats written at the terminal transition stay honest. Without
these two, a row released or swept after stop lands `pending` on a terminal
run — unclaimable (the fence holds) but unreported, a silent hole in "the work
it did not do".

**Losers:**

- **A re-abandon sweep** (periodic `pending→abandoned` on terminal runs):
  eventually-consistent. As the correctness mechanism it leaves a
  resurrection window between release and sweep — a worker claims and fetches
  on a stopped run, which is requests to a supplier after the operator said
  stop. With the claim fence in place it becomes purely a stats-repair pass,
  i.e. a reconciler for writes D2 makes correct at the write — ADR-0026's
  philosophy is the opposite (make the write correct under the row lock).
- **Release-side awareness only** (fence `release`, not `claim`): the claim
  is the reader; fencing one writer while the reader consults nothing leaves
  both the pause mechanism and the terminal guarantee with no home. It also
  still needs the sweep fenced (a dead worker's row returns via the sweep,
  not via release) — two predicates in two writers plus a reader change,
  strictly more than D2's shape.
- **A `paused`-excluding-only fence** (pause handled, terminal runs left
  claimable because "their rows were abandoned anyway"): breaks on D2's own
  release/sweep paths and on any row that reaches `pending` after the stop.
  The fence must be exact: **claimable ⇔ run is `running`.**

**Pause is NOT handled by abandoning rows** — pause keeps every row `pending`;
only the claim fence changes. Stop is terminal and abandons; pause is a
dequeue freeze. Do not conflate them.

### 2. Pause semantics

- **`pause_run(run_id)`**: guarded `UPDATE … SET state='paused' WHERE id = :id
AND state = 'running'`. Touches no queue row, writes no `stop_reason`
  (paused is not terminal — see D5). Claims stop via the fence; in-flight rows
  finish their fetch and close normally.
- **`_ENQUEUE`'s run fence widens** from `r.state = 'running'` to
  `r.state IN ('running', 'paused')`. **Pause freezes dequeue, not
  discovery**: a paused run's in-flight tail still crawls and discovers, and
  dropping those links (the current guard would) makes resume produce a
  silently incomplete crawl — the worst failure mode a pause can have, and
  it leaves no trace.
- **`resume_run(run_id)`**: guarded `paused → running`, then — **in the same
  transaction** — `_FINISH_IF_DRAINED` runs. A run that drained while paused
  (its in-flight tail was the whole remaining queue) can never be closed by a
  row-closing worker afterwards (none of its rows will ever close again, and
  `finish_drained` only fires after a sweep recovery), so without this it
  hangs `running` for ever. With it: resume either finds work (run stays
  running, claims resume) or completes the run with stats, immediately.
- **`finish_if_drained` / `finish_drained` stay fenced on `state = 'running'`**
  — a paused run never auto-transitions. Paused is stable until the operator
  acts. Loser: auto-complete a draining paused run (widen the finish fence to
  paused) — rejected; an operator who paused sees the state they asked for,
  and transitions out of `paused` are operator-driven only (resume, stop).
- **Stop from paused is legal** (D4). Forcing resume-then-stop would make
  rows claimable again for a window — a momentary resurrection to achieve a
  stop, which is the one thing stop must not do.

### 3. `stop_reason` vocabulary

| Terminal path                              | state     | `stop_reason`                                    |
| ------------------------------------------ | --------- | ------------------------------------------------ |
| operator stop (from `running` or `paused`) | `stopped` | `stopped by operator`                            |
| cap breach (2.5, existing)                 | `failed`  | `url cap exceeded: {cap} urls queued for {host}` |

Those are the only non-completed terminal paths that can fire today
(`_FINISH_*` completes; `_HALT_RUN` fails). The invariant — every
non-completed terminal row has a non-null `stop_reason` — is enforced by a
**CHECK constraint**, the honest enforcement:

```sql
ALTER TABLE crawl.runs ADD CONSTRAINT runs_terminal_stop_reason
  CHECK (state IN ('running','paused','completed') OR stop_reason IS NOT NULL);
```

One alembic migration, working `downgrade()`. This also pins structurally
that `paused` carries no `stop_reason` (BUILD_PLAN's done-when says "every
non-`completed` **terminal** state"; `paused` is not terminal — the enum's
terminal set is `completed|stopped|failed`, and pause exists precisely to be
resumable). 2.5's `failed` rows already satisfy the CHECK; no data migration.

### 4. The run transition table — pinned into spec 001 §2

Spec 001 §2 has a domain lifecycle; runs had no equivalent. This slice pins
one (mirroring how 1.2 did domains), as a new **Run lifecycle** block in §2
plus the CHECK in §1's runs DDL:

```
running ──pause──> paused ──resume──> running
   │                  │
   │                  └────stop──────> stopped
   ├──stop──> stopped
   ├──drained──> completed
   └──cap breach (ADR-0040)──> failed

completed | stopped | failed  are terminal; nothing leaves them.
```

**Transitions are guarded SQL predicates, not a `domain/lifecycle.py`-style
pure function.** Every run transition is atomic with row and stats writes in
one transaction (`_HALT_RUN`'s pattern): a pure function plus a separate
write is the check-then-act race the guarded predicate exists to prevent, and
no caller exists that would use a pure function — the callers are SQL
transactions (stop, pause, resume, finish, halt). State that reason in the
spec block so nobody "completes" the symmetry later.

### 5. Stop's shape (adapter)

`PostgresRuns.stop_run(run_id)` — one transaction, **two statements,
ADR-0040's ordering** (the CTE-snapshot lesson: a stats subquery beside the
abandon in one data-modifying CTE reads the pre-abandon snapshot and writes
`pages_abandoned = 0` — the clean finish this slice forbids):

1. run-scoped abandon: `UPDATE crawl_queue SET state='abandoned' WHERE
run_id = :id AND state='pending'` — **no domain filter** (unlike
   `halt_run`, which abandons one domain's rows; see D7);
2. guarded terminal UPDATE: `SET state='stopped', stop_reason='stopped by
operator', finished_at=now(), stats=_STATS WHERE id = :id AND state IN
('running','paused')` — the second statement sees the first's writes.

**Completion race (pinned):** stop fences on `running|paused`;
`finish_if_drained` fences on `running`; `_HALT_RUN` fences on `running`.
Whichever commits first wins and the other's predicate misses — a stopped run
can never be marked completed by its last closing row (its finish finds
`state <> 'running'`), and a completed run can never be stopped (stop's
predicate misses, the CLI reports the run's actual state). No interleaving of
the two produces a stopped-run-marked-completed or the reverse.

**Stats on stop reuse `_STATS`** (0040's precedent); `pages_abandoned` is the
"work it did not do" number and is exact at stop time. **Stated cost, same as
ADR-0040's:** stats are a snapshot at the terminal transition — the in-flight
tail (bounded by workers × `max_concurrency`) closes `done` afterwards and is
not recounted. Bounded, documented in ADR-0041, accepted.

Return shape mirrors `RunHalt`: distinguish "stopped by this call (with
abandoned count and stats)" from "already terminal (which state)". An
operator CLI must never print a lie.

### 6. Entry point

- **`backend/spydra/runctl.py`**, new: `python -m spydra.runctl
<pause|resume|stop> <run_id>`. Prints the transition; for stop, the stats
  (the report of work not done); on a fenced miss, the run's actual state and
  a refusal — never success. Same shape as `spydra.load` (adapter directly,
  no port — the worker is not a caller).
- **Makefile:** `pause-run`, `resume-run`, `stop-run`, each `r=<id>`,
  mirroring `make load` (`$(COMPOSE) run --rm api python -m spydra.runctl
<verb> $(r)`), with the same `usage:` guard when `r` is empty.
- `pause_run` / `resume_run` / `stop_run` live on **`PostgresRuns`**
  (`adapters/postgres/runs.py`) — that file already owns `_STATS` and both
  finish paths, and `halt_run`-on-Frontier was a crawler-caller convenience,
  not the pattern. The **Frontier port is unchanged**: the worker never calls
  these, and 3.4's API wraps the adapter methods.

### 7. Multi-domain runs (2.5 open question 3)

Current truth, measured: **`apply` creates one run per file-load and a file
may name several domains** (`domain_ids` is `sorted(set(domain_ids))`, seeds
from all of them), so multi-domain runs exist constructively today — 2.5's
"every run-creation path today is 1:1" was imprecise. 2.7 needs **nothing**
for them: stop and pause are run-scoped (the whole run, all its domains),
which is the only semantics an operator can drive, and stop's run-scoped
abandon (D5, no domain filter) is exactly that. Per-domain stop needs a
driver that does not exist — **documented here, not built**. The spec note
records this; ADR-0040's seam ("per-domain stop decision") stays open until a
multi-domain UI/API exists.

### 8. ADR-0041 — required

2.5 needed an ADR to add one terminal path; this slice changes the claim's
eligibility (a consult ADR-0026/0034 do not anticipate), introduces the
pause/stop distinction, and adds a schema CHECK. **Number 0041**, file written
by backend, content decided here:

- Title shape: _"The run lifecycle is fenced at the claim"_ (relates-to 0004,
  0026, 0034, 0040).
- Decision: claimable ⇔ run `running` (the fence, its two writer siblings,
  the enqueue widening for paused); pause freezes dequeue not discovery; stop
  is terminal, operator-scoped, in-flight finishes; the CHECK invariant; the
  transition table with guarded-SQL-not-pure-function and why; snapshot-stats
  cost; entry points now (make targets), API wraps in 3.4.
- Alternatives: the three losers from D1, the auto-complete-draining-pause
  loser from D2, test-only enforcement of the invariant (loser: a constraint
  a future writer can violate silently is not an invariant).

## Files this slice owns

Production:

- `backend/spydra/adapters/postgres/runs.py` — `pause_run`, `resume_run`
  (with complete-if-drained), `stop_run`, run-scoped abandon statement
- `backend/spydra/adapters/postgres/frontier.py` — claim fence, sweep CASE,
  release CASE, `_ENQUEUE` run-state widening
- `backend/spydra/runctl.py` — NEW CLI module
- `backend/migrations/versions/<new>_runs_terminal_stop_reason.py` — NEW
  (CHECK constraint; up/down)
- `docs/specs/001-domain-model.md` — §1 runs DDL CHECK; §2 Run lifecycle
- `docs/adr/0041-run-lifecycle-fenced-at-the-claim.md` — NEW (backend writes
  it from "Decided (planner)" §8; filename may tighten, number may not)
- `Makefile` — `pause-run`, `resume-run`, `stop-run`
- `.tasks/feat-2.7-run-lifecycle.md` — this file

Tests (test agent owns; extend rather than multiply where a file exists):

- `backend/tests/adapters/postgres/test_run_lifecycle.py` — NEW: adapter
  contract (stop/pause/resume, fencing, CHECK, the tail races)
- `backend/tests/adapters/postgres/test_frontier.py` or
  `test_frontier_claim_filter.py` — the fence's claim behaviour
- `backend/tests/scheduler/test_worker_process.py` — the real-worker
  acceptance (stop mid-crawl through the subprocess harness, as 1.13 did)
- `backend/tests/test_migrations.py` — CHECK enforced/rejected both ways if
  that is where schema assertions live; else in the new test file

**`backend/spydra/scheduler/` is untouched** — every mechanism is SQL; the
claim loop, crawler and worker need no change. That is a property of the
design, not an omission: keep it true.

## Acceptance (from BUILD_PLAN 2.7's done-when, through the real worker where

the contract demands it)

- [x] A run stopped mid-crawl (real worker crawling) reports the work it did
      not do: pending rows `abandoned`, `state='stopped'`,
      `stop_reason='stopped by operator'`, `stats.pages_abandoned > 0`
- [x] In-flight rows at stop finish their fetch and close `done` (observation
      written); the run is not marked `completed` by their finish
- [x] A row released after stop (SIGTERM / backpressure path) lands
      `abandoned`, and no claim of that run's rows ever succeeds again — the
      run cannot be resurrected
- [x] The fenced domain stays claimable for a _different, running_ run's
      pending rows (the fence is per-row, not per-domain)
- [x] A paused run: claims stop, in-flight rows finish and close `done`, rows
      stay `pending` (none abandoned), no `stop_reason`, state `paused`;
      the in-flight tail's discovery still enqueues (pause freezes dequeue,
      not discovery)
- [x] `resume` returns a paused run to `running` and it crawles to
      `completed` with stats; a run that drained while paused completes on
      resume rather than hanging `running`
- [x] Stop from `paused` is legal; pause/stop on a terminal run changes
      nothing and reports the actual state (CLI never lies)
- [x] `stats` populated on every terminal path: completed (existing), failed
      cap-breach (existing), stopped (new)
- [x] The CHECK rejects a `stopped`/`failed` row with NULL `stop_reason` and
      accepts `running`/`paused`/`completed` with NULL; migration runs both
      ways
- [x] Spec 001 §2 carries the run transition table; every valid edge tested,
      ≥3 invalid transitions rejected (the guarded UPDATEs miss)
- [x] `make pause-run r=<id>` / `resume-run` / `stop-run` run through the api
      container and print honest outcomes

## Handoff log

- planner — contract above; branch from `feat/2.6-mega-menu-guard`. One
  planner-level correction recorded: 2.5 OQ3's "run-creation is 1:1" is
  imprecise — `apply` is 1 run : N domains per file (D7). ADR-0041 content
  is §8; backend writes the file. **First file:**
  `backend/spydra/adapters/postgres/runs.py`.
- backend — built, as pinned: claim fence (one EXISTS inside ADR-0034's,
  `frontier.py` `_CLAIM`; both ADR-0026 locks untouched); sweep CASE +
  release CASE route non-`running`-run rows to `abandoned` (sweep joins
  runs in the expired CTE with `FOR UPDATE OF q` so only queue rows lock,
  as before); `_ENQUEUE` fence widened to `('running','paused')`;
  `PostgresRuns.pause_run/resume_run/stop_run` + `RunTransition` (mirrors
  `RunHalt`: transitioned / actual state on miss / abandoned / stats) —
  **adapter-direct, no Runs port introduced** (task §6: worker is not a
  caller, 3.4's API wraps the adapter, Frontier port unchanged); stop is
  two-statements-one-transaction per ADR-0040 (abandon first, `_STATS`
  second), stop from `running|paused`, finishes stay `running`-fenced;
  resume runs `_FINISH_IF_DRAINED` in the same transaction as the
  `paused→running` write. `spydra/runctl.py` (load.py precedent: sync
  entry, `asyncio.run`, adapter direct; refuses with the actual state on
  a miss, exit 1). Makefile `pause-run|resume-run|stop-run r=` with the
  `usage:` guard. Migration `e5f2c9a71b34_runs_terminal_stop_reason`
  (CHECK, up/down; hand-written per 2.5 — autogenerate misses CHECKs).
  ADR-0041 written from §8, indexed in README. Spec 001: §1 runs DDL
  CHECK; §2 new "Run lifecycle" subsection (transition table,
  guarded-SQL-not-pure-function reason, stop_reason vocabulary, D7
  multi-domain note). `make lint` + `make test-api` green (1092 passed).
  **Two deviations, both forced by the pinned design, both in
  `test_enqueue_guard.py` (production scope otherwise):** (1) the 2.3-era
  parametrize `["completed","stopped","paused"]` on
  "a run that is not running gets nothing" contradicts D2's pinned
  widening — `paused` removed, test renamed `test_a_terminal_run_gets_nothing`;
  the positive paused-discovery case is the test agent's. (2) that test's
  fixture parked a run in `stopped` with no `stop_reason` — the new CHECK
  (correctly) rejects it; the fixture now writes one. No scheduler file
  touched; `scheduler/` untouched by design holds.
- backend (review) — review verdict fixed, all three findings. **F1
  (BLOCKING), serialise the routing writers against run transitions** —
  implemented as the reviewer decided (FOR SHARE, the 2.3/`_ENQUEUE`
  pattern, on the run row), with two shape calls recorded here because the
  reviewer's own probe forced them: (a) `release()` takes the share lock
  as a preceding statement exactly as prescribed, but the **sweep's share
  lock lives in the expired CTE's locking clause**
  (`FOR UPDATE OF q SKIP LOCKED FOR SHARE OF r`) rather than a preceding
  statement — a preceding lock-statement holds a _different_ snapshot's
  candidate set, so a row expiring between the two statements of one
  transaction would route unlocked (the same race, narrower), and
  in-statement is the literal `_ENQUEUE` precedent shape; the empty case
  locks nothing by construction, so the skip-if-empty guard is moot.
  (b) **the terminal writers lock before their abandon**: `stop_run` and
  `halt_run` now take the run row `FOR UPDATE` (guarded by their own
  transition predicate) as the transaction's FIRST statement. Without
  this, share locks on the routing side only narrow the window — a stop's
  abandon (first statement, `crawl_queue` only) runs before its run-row
  UPDATE ever blocks on the share lock, misses the `in_flight` row the
  release holds, and the release commits it `pending` onto the stopped
  run; the probe's adversarial interleaving fails without the writer-side
  lock. This is the other half of the cited precedent (there, the share
  lock exists "so its abandon sees these rows" — same ordering, run row
  instead of domain row). `halt_run` gets the same lock because the
  `failed` edge has the identical shape and hole. Probe (two engines,
  deleted after): release-holds-share + concurrent stop → row `abandoned`
  (stop parked pre-abandon, release routed `pending`, stop's abandon
  caught the committed row, `abandoned=1`); stop-commits-first → release
  routes `abandoned`. Both pass. ADR-0041: new "routing is serialised"
  decision paragraph (mechanism, the unlocked-read interleaving in one
  sentence, both halves); stated-cost + consequences now carry the
  released-`abandoned`-not-recounted half of the tail (the SIGTERM 2-of-3)
  — **F3**. **F2**: `test_run_lifecycle.py` docstring pointer →
  `test_run_control.py`. `make lint` + `make test-api` green
  (1149 passed, 2 skipped) with the routing tests unchanged — the locking
  changed no observable behaviour beyond the race.
- backend (re-review) — blocker 1 fixed: `_ENQUEUE`'s run-state check was
  the last unlocked run read feeding a queue write; a stop committing
  after the enqueue's snapshot landed discovered rows `pending` on a
  terminal run — the identical class the routing serialisation closed.
  The check moved into a locking CTE at the top of `_ENQUEUE`
  (`WITH run AS (SELECT id FROM crawl.runs WHERE id = :run_id AND state
IN ('running','paused') FOR SHARE OF r)`; consumed as
  `AND EXISTS (SELECT 1 FROM run)`), one statement preserved. The domain
  `FOR SHARE` stays inline (it fences the 2.3 domain halts); the run lock
  fences stop/halt/finish — same EvalPlanQual re-read the sweep's
  `FOR SHARE OF r` uses, cited in the comment. **Correction to D1**: its
  "the guarded enqueue has carried an identical run-state EXISTS since
  2.3" is now doubly stale — the predicate is a locking CTE, not a bare
  EXISTS, and the fence is a lock, not just a filter. D1 left as written
  (planner text; house style corrects in the handoff, as the planner's
  own OQ3 correction did); artifacts aligned: ADR-0041's serialisation
  paragraph gains the discovery-writer bullet and the extended
  "true at the write" sentence; spec 001 §2's Run lifecycle intro
  rewritten for routing locks + enqueue lock (it still attributed the
  invariant to the routing CASEs alone). Verified with a throwaway
  two-engine probe (deleted): with a terminal writer holding the run row
  uncommitted, the enqueue BLOCKED behind the CTE's `FOR SHARE` and, once
  the stop committed, re-read and inserted nothing (`added=0`). Blocker 2
  (permanent two-engine interleaving tests) left to the test agent per
  the review.
- test — 57 tests, three files, all green under `make test-api`
  (1149 passed, 2 skipped; 1092 before). `tests/adapters/postgres/
test_run_lifecycle.py` (41): the fence (claim refuses paused + all three
  terminal states with a pending row; per-run-not-per-domain control),
  sweep routing (terminal→abandoned, paused→pending, `attempts >= max`
  still wins on a stopped run), release routing (after-stop→abandoned,
  under-pause→pending), the positive paused-discovery enqueue the backend
  left, every valid transition edge (pause/resume/stop/finish/halt) and
  the misses as refusals reporting the actual state, stop's abandoned
  count and exact `pages_abandoned` snapshot, resume's same-transaction
  drained-finish, both finish paths' `running` fence, the CHECK
  (rejects `stopped`/`failed` bare, accepts `running`/`paused`/`completed`
  bare and terminal-with-reason), and the completion race as two real
  engines (a finish blocked on an uncommitted stop misses; a stop blocked
  on an uncommitted finish misses). `tests/scheduler/test_run_control.py`
  (5, real worker): stop mid-crawl (abandoned+done both present, no
  pending, stats exact, tail closes done without completing the run,
  requests freeze with the worker up, domain `active`, every request
  accounted done); stop + SIGTERM cancelling a 15 s fetch (released row
  `abandoned`, run `stopped`); pause freezes claiming and resume crawls to
  `completed`; the deterministic paused-tail test (claim seed → pause →
  crawl in-process: row closes `done`, observation written, discovery
  enqueues `pending` under pause, nothing claimable until resume); and
  the drained-while-paused run (single slow page, pause in flight, tail
  closes, finish refuses, resume completes with stats).
  `tests/test_runctl.py` (11, subprocess `python -m spydra.runctl`):
  pause/resume/stop happy paths — stop's output names the abandoned count
  and carries `pages_abandoned` — six wrong-state misses (exit 1, actual
  state named), no-such-run, and the usage guard. **Mutations, each red
  then restored green:** M1 claim fence removed (5 red); M2 fence narrowed
  to `<> 'stopped'` (paused claimable — 4 red); M3 sweep terminal branch
  removed (3 red); M4 release routing dropped (1 red); M5 stop's
  statements swapped (stats snapshot 0 abandoned — 3 red, adapter + both
  worker tests); M6 stop fence widened to `completed` (3 red incl. the
  blocked-stop race and the CLI); M7 resume without the drained-finish
  (2 red); M8 CHECK dropped in the test DB (2 red; restored with the
  migration's exact text); M9 `_ENQUEUE` back to `running`-only (2 red);
  M10 `stop_reason` mangled — **initially GREEN, a vacuous test**: the
  first version asserted against the imported `STOP_REASON_OPERATOR`,
  comparing the constant to itself; fixed to pin spec 001 §2's literal
  `"stopped by operator"` (4 red after, green restored). **One measured
  behaviour worth knowing (not a defect):** a row released after stop
  lands `abandoned` in the queue but is NOT recounted in the stop-time
  stats snapshot (`pages_abandoned` 2 of 3 rows in the SIGTERM test) —
  ADR-0041's stated bounded snapshot cost, the same one the tail's `done`
  closes pay on `pages_crawled`; the test pins it with a comment. The
  scheduler file is named `test_run_control.py`, not
  `test_run_lifecycle.py`, because pytest imports test modules by basename
  and the adapter file owns that name. Migration-both-ways stays with
  `test_migrations.py`'s AST symmetry guards + CI's `migrate-down` (that
  file's own header explains why a suite test must not run `downgrade`).
- test (serialisation) — the reviewer's re-review finding closed: the
  run-transition locks were shipped untested (deleting any left the suite
  green). Six permanent interleaving tests, section 8 of
  `test_run_lifecycle.py` (47 tests in the file now), all on the
  deterministic two-engine harness (`_waiting_on_a_lock` + an uncommitted
  transaction, with `waited and not done_early` asserted so a test cannot
  pass against a writer that never blocked): **(1)** release holds the run
  row `FOR SHARE`, a stop parks on its `FOR UPDATE` pre-abandon → the
  release routes `pending` under the still-`running` run and commits, the
  stop's abandon catches the committed row → `abandoned`, `abandoned == 1`,
  stats `pages_abandoned == 1`, run `stopped`; **(2)** the mirror order —
  a stop holds `FOR UPDATE` uncommitted, the release's preceding share
  lock WAITS, wakes on commit and routes `abandoned`; **(3)** the sweep's
  `FOR SHARE OF r` waits out an uncommitted stop and re-reads terminal
  (EvalPlanQual) → the expired row routes `abandoned`, never
  `pending`-on-terminal; **(4)** an enqueue arriving behind an uncommitted
  stop blocks in the `run` CTE, wakes, re-reads `stopped`, inserts nothing
  (`added == 0`, no row — fixture domain `active` on purpose: `discovered`
  short-circuits before the run lock); **(5)** the enqueue-commits-first
  mirror — the enqueue's share lock parks the stop until its rows are
  committed, so the stop's abandon counts them (`abandoned == 1`); **(6)**
  `halt_run`'s lock-first, the `failed`-edge twin of (1). **Mutations, each
  red then restored green:** ML1 release `FOR SHARE` deleted → test 2 red
  (the release never waits; routes `pending` onto the stopped run); ML2
  sweep `FOR SHARE OF r` deleted → test 3 red; ML3 enqueue CTE lock
  deleted (filter kept) → test 4 red; ML4 `stop_run` lock-first deleted →
  tests 1 AND 5 red — the exact probe failure the backend described (the
  abandon runs while parked on the run row, misses the in-flight row, the
  release commits it `pending` after the stop; and the stop no longer
  waits for an uncommitted enqueue); ML5 `halt_run` lock-first deleted →
  test 6 red. **Coverage notes, stated honestly:** under ML1 test 1 stays
  green — the stop's abandon then blocks on the _queue row_ the release's
  routing UPDATE holds and still catches it, so the release share lock's
  matching red is test 2 and the writer-side lock's is test 1 (ML4 proved
  it with two reds); under ML3 test 5 stays green for the same
  queue-row-locking reason, so the enqueue lock's matching red is test 4.
  Every lock has a deterministic red; the queue-row locks are a second,
  narrower net the interleavings do not need to rely on. `make lint` +
  `make test-api` green (1155 passed, 2 skipped).

## Open questions

- none blocking. Flagged for the human (planner decisions taken, reversible
  cheaply): the exact string `stopped by operator` (no actor/timestamp
  suffix); resume shipping now alongside pause (a pause nothing can resume
  is a stop with extra steps); the snapshot-stats cost (same as ADR-0040's
  breach halt — a post-tail recompute was rejected as a reconciler for
  writes D2 makes correct at the write).
