# 0041 — The run lifecycle is fenced at the claim

**Status:** Accepted · 2026-10-23
**Relates to:** [ADR-0004](0004-stop-on-block.md) (abandon, never delete),
[ADR-0026](0026-claim-locks-the-domain-row.md) (the claim's shape),
[ADR-0034](0034-claim-only-a-domain-with-work.md) (the claim's work check),
[ADR-0040](0040-cap-breach-is-a-run-scoped-halt.md) (the first
non-completed terminal transition, and the ordering this ADR reuses)
**Amends:** `docs/specs/001-domain-model.md` §1–§2 (runs DDL CHECK; run
lifecycle block)

## Context

`run_state` has had `paused` and `stopped` in its enum since the first
migration, but nothing could move a run into either: runs were born
`running` and left only by `completed` (drained) or `failed` (cap breach,
ADR-0040). BUILD_PLAN 2.7 gives the operator the wheel — pause, resume,
stop — and 2.5's ADR needed writing for one terminal path, so this one
changes three things that each needed deciding:

1. what stops a worker from claiming a paused or stopped run's rows;
2. what pause and stop each mean for rows that are already in flight, and
   for the links those rows discover;
3. how "every non-completed terminal run names why it ended" is kept true.

Pause and stop are different answers, not two spellings of one. Pause is a
dequeue freeze that the operator can undo; stop is terminal. Conflating
them — pausing by abandoning rows — would make resume crawl a subset of
what the operator paused, silently.

## Decision

**Claimable ⇔ the run is `running`.** One predicate inside the claim's
ADR-0034 work-check EXISTS: a pending row counts as work only if its run is
`state = 'running'`. That single predicate buys both states — a terminal
run's rows stop being claimable (the domain is skipped entirely rather than
locked-then-empty) and a paused run's stop being claimable without being
touched, which is the distinction pause exists to make. Against ADR-0026
the cost is one PK probe per pending-row candidate inside an EXISTS that
already runs per eligible domain; the guarded enqueue has carried an
identical run-state EXISTS since 2.3.

The same rule at the **two other places a row can leave `in_flight` back to
claimable**: the lease sweep and the release path (backpressure, SIGTERM,
a claim that raced the signal) each send a row of a non-`running` run to
`abandoned` instead of `pending` — `attempts >= max` still wins in the
sweep, because an exhausted row failed and that is accurate. Without these
two, a row released or swept after stop lands `pending` on a terminal run:
unclaimable (the fence holds) but unreported — a silent hole in "the work
it did not do", the number stop exists to report.

**The routing is serialised against the transition, under row locks.** The
first version of the two siblings above read `runs.state` from an unlocked
snapshot, and a stop committing between that read and the routing
statement's commit put the row `pending` on a terminal run after all —
unclaimable, permanently unreported, and invisible to a second stop (which
abandons it but rewrites no stats and tells nobody). The fix is the
2.3/`_ENQUEUE` pattern (`_ENQUEUE` share-locks the domain row so a halt's
abandon waits and sees its rows) turned on the run row, and it needs both
halves:

- **The routing writers lock first.** `release` takes `FOR SHARE` on the
  item's run row before its routing statement; the sweep share-locks the
  run rows _in_ its expired CTE's locking clause (`FOR UPDATE OF q SKIP
LOCKED FOR SHARE OF r`), so the routing CASE's read and the row's fate
  are one atomic decision — a preceding lock-statement would hold a
  different snapshot's candidate set and route a row that expired between
  the two statements unlocked.
- **The terminal writers lock before their abandon.** `stop_run` and
  `halt_run` take the run row `FOR UPDATE` (guarded by their transition's
  own predicate) _before_ abandoning, which is the half the share locks
  alone lack: without it, a stop's abandon — its first statement, touching
  only `crawl_queue` — runs while a release still holds the row
  `in_flight`, misses it, and the release commits it `pending` onto the
  run the stop then closes. With both halves, every interleaving routes
  `abandoned`: the routing writer either commits first (and the terminal
  writer's abandon sees the row it returned to `pending`) or waits and
  reads the terminal state.

With them, **a terminal run holds no pending rows** is true at the write,
and the stats written at the terminal transition stay honest.

**Pause freezes dequeue, not discovery.** `pause_run` is a guarded
`running → paused` UPDATE: no queue row is touched, no `stop_reason`
written (paused is not terminal). The enqueue's run fence widens from
`= 'running'` to `IN ('running', 'paused')`, because a paused run's
in-flight tail still crawls and discovers, and dropping those links would
make resume produce a silently incomplete crawl — the worst failure mode a
pause can have, and it leaves no trace. `resume_run` is a guarded
`paused → running` followed, in the same transaction, by the
drained-finish: a run that drained while paused (its in-flight tail was the
whole remaining queue) is closed by nothing else — none of its rows will
ever close again — so without this it hangs `running` for ever. Both finish
paths stay fenced on `state = 'running'`; a paused run never
auto-transitions. Stop from `paused` is legal, and forcing
resume-then-stop to reach it would be a momentary resurrection — claims
flowing again for a window — to achieve the one thing stop must not do.

**Stop is terminal, operator-scoped, and in-flight finishes.** On stop, a
run's pending rows are abandoned and reported; rows already in flight
finish their fetch and close `done` normally. `stop_run` is one
transaction, two statements, ADR-0040's ordering: run-scoped abandon of
pending rows first (no domain filter — stop is operator-scoped over the
whole run, all its domains), then the guarded
`state IN ('running','paused') → stopped` with
`stop_reason = 'stopped by operator'` and `_STATS`. The order is
load-bearing for the same reason ADR-0040's is: a stats subquery beside the
abandon in one data-modifying CTE reads the pre-abandon snapshot and writes
`pages_abandoned = 0` — the clean finish stop exists to prevent.

The completion race closes itself: stop fences on `running|paused`; the
finish paths and the cap halt fence on `running`. Whichever commits first
wins and the other's predicate misses — a stopped run can never be marked
`completed` by its last closing row, and a completed run can never be
stopped.

**The invariant is a CHECK constraint** (spec 001 §1):
`state IN ('running','paused','completed') OR stop_reason IS NOT NULL`.
Every non-completed terminal row names why it ended, structurally;
`paused` is deliberately on the NULL side — it is resumable, not terminal.
2.5's `failed` rows already write a reason, so there is no data migration.

**The transition table is guarded SQL, not a pure function.** Runs get a
lifecycle block in spec 001 §2 (mirroring how 1.2 did domains), but unlike
the domain lifecycle there is no `domain/lifecycle.py` equivalent: every
run transition is atomic with its row and stats writes in one transaction
(`_HALT_RUN`'s pattern), a pure function plus a separate write is the
check-then-act race the guarded predicate exists to prevent, and no caller
exists for a pure function — the callers are SQL transactions (stop, pause,
resume, finish, halt).

**Stated cost, same as ADR-0040's:** stats are a snapshot at the terminal
transition, and the tail is not recounted in either direction. Rows
in flight at stop (bounded by workers × `max_concurrency`) close `done`
after the snapshot; rows _released_ after it — the SIGTERM worker handing
its rows back, which the serialised routing now sends to `abandoned` — are
counted by neither the snapshot nor the abandoned-batch number stop
reports. A run stopped with three rows in flight whose SIGTERMed worker
releases two of them reports them `abandoned` but they never enter the
snapshot's `pages_abandoned`; bounded by the same tail, documented, and
preferred to a reconciler — ADR-0026's philosophy is to make the write
correct under the row lock, not to repair it later.

**The operator entry point ships now, not in 3.4:** `PostgresRuns` gained
the three lifecycle methods, and `python -m spydra.runctl <verb> <run_id>`
plus `make pause-run|resume-run|stop-run r=<id>` drive them through the api
container. 3.4's API wraps the same adapter calls. The **Frontier port is
unchanged** — the worker never calls these, and `halt_run`-on-Frontier was
a crawler-caller convenience, not the pattern.

## Consequences

- A stopped run cannot be resurrected: no claim of its rows can succeed
  again, and every path that would return a row to `pending` routes it to
  `abandoned` instead. The fence is per-row, not per-domain — a fenced
  domain stays claimable for a _different, running_ run's pending rows.
- Pause costs nothing the operator cannot see: rows stay `pending`, the
  in-flight tail finishes and its discovery still enqueues, and resume
  either finds work or completes the run with stats immediately.
- `pages_abandoned` is exact for everything pending at stop; the tail is
  not recounted in either direction — rows in flight close `done` after
  the snapshot, and rows the SIGTERM path releases after it land
  `abandoned` outside both the snapshot and the reported count. The run
  report states the work not done; the run row does not chase the tail.
- A run that drained while paused is completed by resume, not by the
  sweep: `finish_drained`'s recovery role is unchanged, but resume is what
  closes a deliberately-paused run, which keeps transitions out of
  `paused` operator-driven only.
- Multi-domain runs exist constructively (a file-load's `apply` creates
  one run over N domains), and 2.7 needs nothing for them: stop and pause
  are run-scoped over all of a run's domains, which is the only semantics
  an operator can drive. Per-domain stop needs a driver that does not
  exist; ADR-0040's seam for it stays open until a multi-domain UI/API
  does.
- Cost: the claim, sweep and release each grew a run-state lookup
  (PK probe / join / scalar subquery). All three are per-candidate probes
  on indexed PKs against a table with one row per run — noise next to the
  enqueue, which has paid the same probe per batch since 2.3.

## Alternatives considered

- **A re-abandon sweep** (periodic `pending → abandoned` on terminal runs)
  as the correctness mechanism. Eventually consistent: it leaves a
  resurrection window between release and sweep in which a worker claims
  and fetches on a stopped run — requests to a supplier after the operator
  said stop. With the claim fence it degenerates into a stats-repair pass,
  a reconciler for writes made correct at the write, which is the opposite
  of ADR-0026's philosophy.
- **Release-side awareness only** (fence the release, not the claim). The
  claim is the reader; fencing one writer while the reader consults
  nothing leaves both the pause mechanism and the terminal guarantee with
  no home — and it still needs the sweep fenced, because a dead worker's
  row returns via the sweep, not the release: two predicates in two
  writers plus a reader change, strictly more than the chosen shape.
- **A `paused`-excluding-only fence** (pause handled, terminal runs left
  claimable on the theory that their rows were abandoned anyway). Breaks
  on the release and sweep paths and on any row that reaches `pending`
  after the stop. The fence must be exact: claimable ⇔ run is `running`.
- **Auto-complete a draining paused run** (widen the finish fence to
  admit `paused`). Rejected: an operator who paused sees the state they
  asked for; transitions out of `paused` are operator-driven only (resume,
  stop). The drained-while-paused run is completed by resume instead.
- **Test-only enforcement of the terminal invariant.** A constraint a
  future writer can violate silently is not an invariant; the CHECK makes
  the violation loud at the write, which is where it is cheap to fix.
