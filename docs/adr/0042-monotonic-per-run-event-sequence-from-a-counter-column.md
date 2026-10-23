# 0042 — Monotonic per-run event sequence from a counter column

**Status:** Accepted · 2026-10-24
**Relates to:** [ADR-0002](0002-postgres-as-queue.md) (Postgres is the queue
and the database — no second datastore), [ADR-0008](0008-ports-and-adapters.md)
(the ports split Frontier exists for), [ADR-0012](0012-sse-for-progress.md)
(the bounded log exists for SSE backfill; this sets its bound),
[ADR-0040](0040-cap-breach-is-a-run-scoped-halt.md) (the cap halt whose
`run_state` row this replays), [ADR-0041](0041-run-lifecycle-fenced-at-the-claim.md)
(the lifecycle whose transitions this replays; the serialisation locks the
seq reservation rides alongside)
**Amends:** `docs/specs/001-domain-model.md` §1 (runs DDL gains
`next_seq`), `docs/specs/002-scheduler.md` §7 (progress cadence)

## Context

`run_events` has existed since 1.1 with nothing writing it: spec 005 §3's
SSE endpoint (3.6) replays it, and until then the table is scaffolding.
BUILD_PLAN 2.8 is the writer. Four things needed deciding, none of them
obvious:

1. how `seq` is assigned when two workers can emit for one run
   concurrently — `UNIQUE (run_id, seq)` makes a duplicate a hard error;
2. what a gap in the sequence means to a reconnecting SSE client;
3. how big the log may grow and what trims it (ADR-0012 called the bound
   "a real piece of work" and left it unset);
4. which component writes which event — some events are facts about a
   transaction that already happened, others are projections of rows that
   already exist.

## Decision

**`seq` comes from a counter column, `runs.next_seq`, reserved atomically.**
Every emission, in whatever transaction it runs, is two statements:

```sql
UPDATE crawl.runs SET next_seq = next_seq + 1 WHERE id = :run_id
RETURNING next_seq;                                   -- reserve
INSERT INTO crawl.run_events (run_id, seq, kind, payload)
VALUES (:run_id, :seq, :kind, :payload);              -- spend
```

Reservation and insert share one transaction, so a rollback discards both
— **the sequence is monotonic AND gap-free by construction**: `seq` is the
ordinal of every event the run has ever emitted. Duplicates cannot occur
at all (the UPDATE's own row lock serialises reservers), which is why
there is no retry policy to pin.

**Gap-free is deliberate, not incidental.** SSE `id:` needs monotonic;
gaps would change reconnect semantics — a client that sees `id: 1041`
after `id: 1039` cannot tell "one lost" from "one trimmed". Gap-free makes
trim detection arithmetic: `oldest retained seq > Last-Event-ID + 1` ⇒
truncated, no protocol change, no synthetic marker event. A reconnect
below the oldest retained seq is backfilled with the entire retained
window.

**Concurrency cost, stated:** every emission serialises on the run row for
one statement. Event rate is bounded by politeness (≈1 page per domain per
crawl delay) plus the progress throttle — a handful of statements a second
across the worker. It is the same row 2.7's writers already serialise on.

**The log is bounded at keep-last-5,000 per run** (the operator's number; a
knob, tuned later against real runs), trimmed by one set-based DELETE in
the claim loop's existing maintenance beat, beside the lease sweep. **Live
runs only** (`running|paused`): a terminal run emits nothing more, so
trimming it could only lose events. Per run the trim is one backward probe
on `ix_run_events_run_seq`; a run under the bound deletes nothing. A
terminal run therefore retains at most 5,000 + ε, where ε is the events
between the last sweep trim and termination (bounded by one trim
interval's emissions) — documented slop on a knob. The terminal
`run_state` event is always retained; it is the newest row.

**Emission is split: transactional for `run_state`, projected for the
rest.** `run_state` events are written inside the transition transactions
(`runs.py`'s pause/resume/stop/finishes, `frontier.py`'s `halt_run`) — the
guard that makes the transition honest makes the event honest: **a
`run_state` row exists iff the transition happened.** A caller-side emit
could crash between transition-commit and event-insert and lose the
terminal event for ever — the one event a reconnecting client cannot live
without. It also answers "who emits for a run finished by
`finish_drained`, which no worker owns": the transition does, in the
statement's own transaction. `page`, `progress` and `domain_state` are
emitted by the worker after the durable write they project
(observation/queue-close/domain row), each in its own short transaction —
losing one to a crash is acceptable, the rows are the facts, and the
observation path must not hold locks while writing a different table.

**The emission set** (payload keys are spec 005 §3's, nothing speculative):

| kind           | emits when                                                                                                          | payload                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `page`         | a queue row closes `done` or final `failed`. Not on retry-`pending`, not on `release`, not on `abandoned`           | `{url, status, strategy, fields, ok}`                 |
| `progress`     | after each page close that moved a domain's counts, throttled to ≤1 per (run, domain) per second, in-process        | `{domain, queued, in_flight, done, failed, depth}`    |
| `domain_state` | a domain actually moved: the three-403 pause; the 1.11 `BREAK`/`NEVER_MATCHED` halts                                | `{domain, state, reason}`                             |
| `run_state`    | every run transition: pause, resume, stop, cap-halt, both finishes                                                  | `{state, stop_reason?, stats?}` — `stats` on terminal |
| `asset`        | **not emitted until 5.2.** Nothing drains `asset_queue`; the only honest payload today is a live gauge, not history | —                                                     |

Why the silent kinds emit nothing: a stop or cap breach abandons up to the
whole remaining queue at once, and thousands of events in one burst is
exactly what spec 005 §3's coalescing line forbids — `run_state.stats.
pages_abandoned` carries the number. A retry is not an outcome; a release
is backpressure, nothing happened.

**Volume discipline (spec 009):** events are rows, not log lines. Emission
adds no log line above `debug`; 1.13's line budget is untouched. Growth is
bounded by page rate plus ≤1/s/domain from progress; the 5,000-per-run
bound keeps the table honest past that.

**Adapter-direct, no `ports/` entry**, on 2.7's precedent and the
codebase's own shape: the worker already consumes `PostgresRuns` and the
other repositories directly. Frontier is a port because it is the
reversible-Postgres decision (ADR-0002/0008), not because everything the
worker touches is one. A one-implementation port is an untested
abstraction.

## Consequences

- The migration backfills `next_seq` from each run's `max(seq)`, so it is
  correct for any database state it meets, not just today's empty table.
- The progress throttle is per worker process: two replicas emit at most
  2/s/domain. Spec 005 §3 states the one-per-second coalescing for the
  endpoint — 3.6 can coalesce further on read.
- The 7-day post-run purge (spec 005 §3) is retention, not bounding, and
  is deliberately not this slice: nothing consumes events before 3.6.
- No `emit_many`: no call site emits more than one event at a time. A
  per-batch reservation (`next_seq = next_seq + :n`, spend `n-k+1..n`) is
  the one-line upgrade if a batching call site ever appears.
- Every `run_events` emission costs one extra statement serialised on the
  run row — acceptable at the stated rates, and the acceptance test is two
  real engines emitting concurrently.

## Alternatives considered

- **`INSERT … SELECT coalesce(max(seq),0)+1` with retry on unique
  violation** — needs a retry policy (N, backoff, overflow), pays a retry
  storm exactly when two workers race, and is trim-fragile: `max(seq)`
  reads the table, so any future change that deletes a run's highest row
  (a purge, a smarter trim) silently restarts the sequence at 1 and
  duplicates begin.
- **A locked `SELECT max` per transaction** (run row `FOR UPDATE`, read,
  insert) — the same `max` fragility, more statements, and it takes the
  run row exclusively on every page event, queueing behind 2.7's
  `FOR UPDATE` terminal writers and the `FOR SHARE`
  routing/enqueue writers: emission would contend with the queue itself.
- **`pg_advisory_xact_lock(run_id)`** — works, but imports a lock
  namespace nothing in this repo uses, still needs `max(seq)+1`
  (trim-fragile) or a counter anyway, and is one more statement per emit.
- **Per-worker batched blocks** (reserve 100 seqs, spend locally) — gaps
  on worker death, and gaps are the semantics rejected above.
- **A one-shot trim folded into every terminal transition** (five call
  sites) — buys exactness at the bound nobody needs: the ε it removes is
  one trim interval's emissions on a knob already marked "tuned later".
- **A `run_events` port** — a one-implementation port is an untested
  abstraction; the worker already consumes concrete adapters.
- **Unthrottled progress** — a busy run emits one event per page close,
  thousands per minute, which is the burst spec 005 §3's coalescing line
  exists to prevent, arriving at the writer instead of the reader.
