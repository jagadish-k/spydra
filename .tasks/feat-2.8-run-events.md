# feat/2.8-run-events

**Task:** BUILD_PLAN 2.8 · **Spec:** 001 §1 (`run_events` DDL — table,
`UNIQUE (run_id, seq)`, `ix_run_events_run_seq` all exist since 1.1; the five
kinds), 002 §7 (depth on every progress event), 005 §3 (what the SSE consumer
3.6 will need — read for the writer, do **not** build the endpoint), 009 §1/§5
(volume discipline: events are rows, the emission adds no log lines)
**ADRs that constrain this:** 0002 (Postgres is the queue and the database —
no second datastore), 0003 (the pools), 0012 (the bounded log exists for SSE
backfill), 0040 (the cap halt whose `run_state` row this replays), 0041 (the
lifecycle whose transitions this replays; the serialisation locks the seq
reservation rides alongside), **0042 (new — backend writes it, content pinned
in "Decided (planner)" §6)**
**Stacked on:** `feat/2.7-run-lifecycle` (PR pending)

## Decided (user)

- **The log is bounded at keep last 5,000 events per run, trimmed in the
  existing sweep** — a constant, tuned later against real runs.

## Decided (planner)

Verified on `feat/2.7-run-lifecycle` @ `616bb83`, clean tree (three untracked
`pr-*-body.md`, no slice in flight). The worker consumes concrete adapters
already (`Repositories` in `scheduler/crawl.py`: `PostgresDomains`,
`PostgresPages`, `PostgresTemplates`, `PostgresObservations`, `PostgresRuns`;
`PostgresAssets` in `pools.py`) — Frontier is the exception, not the pattern.

### 1. `seq` — a per-run counter column, reserved atomically

**`runs.next_seq BIGINT NOT NULL DEFAULT 0`** (one Alembic revision, both
ways, backfilled `next_seq = coalesce((SELECT max(seq) FROM
crawl.run_events e WHERE e.run_id = runs.id), 0)` — the table is empty today,
but the migration must be correct for any DB state it meets). Every emission,
in whatever transaction it runs, is two statements:

```sql
UPDATE crawl.runs SET next_seq = next_seq + 1 WHERE id = :run_id
RETURNING next_seq;                                   -- reserve
INSERT INTO crawl.run_events (run_id, seq, kind, payload)
VALUES (:run_id, :seq, :kind, :payload);              -- spend
```

Reservation and insert share one transaction, so a rollback discards both —
**the sequence is monotonic AND gap-free by construction**: `seq` is the
ordinal of every event the run has ever emitted. Duplicates cannot occur at
all (the UPDATE's own row lock serialises reservers), which is why there is
no retry policy to pin.

**Why gap-free is deliberate, not incidental.** SSE `id:` needs monotonic;
gaps would change reconnect semantics — a client that sees `id: 1041` after
`id: 1039` cannot tell "one lost" from "one trimmed". Gap-free makes trim
detection arithmetic (§4): `oldest retained seq > Last-Event-ID + 1` ⇒
truncated, no protocol change.

**Losers:**

- **`INSERT … SELECT coalesce(max(seq),0)+1` with retry on unique violation**
  — needs a retry policy (pinning N, backoff, overflow), pays a retry storm
  exactly when two workers race, and is trim-fragile: `max(seq)` reads the
  table, so any future change that deletes a run's highest row (a purge, a
  smarter trim) silently restarts the sequence at 1 and duplicates begin.
- **A locked `SELECT max` per transaction** (run row `FOR UPDATE`, read,
  insert) — the same `max` fragility, more statements, and it takes the run
  row exclusively on every page event, queueing behind 2.7's `FOR UPDATE`
  terminal writers and the `FOR SHARE` routing/enqueue writers: emission
  would contend with the queue itself.
- **`pg_advisory_xact_lock(run_id)`** — works, but imports a lock namespace
  nothing in this repo uses (verified: no advisory call anywhere), still
  needs `max(seq)+1` (trim-fragile) or a counter anyway, and is one more
  statement per emit.
- **Per-worker batched blocks** (reserve 100 seqs, spend locally) — gaps on
  worker death, and gaps are the semantics rejected above.

**Concurrency cost, stated:** every emission serialises on the run row for
one statement. Event rate is bounded by politeness (≈1 page per domain per
crawl delay) plus the progress throttle (§3) — a handful of statements a
second across the worker. It is the same row 2.7's writers already serialise
on; the acceptance test is two real engines emitting concurrently
(`test_enqueue_guard.py` / `test_run_lifecycle.py` §8's two-engine shape).

### 2. Emission — transactional for `run_state`, projected for the rest

- **`run_state` events are written inside the transition transactions.**
  `pause_run`/`resume_run`/`stop_run`/`finish_if_drained`/`finish_drained`
  (`adapters/postgres/runs.py`) and `halt_run`
  (`adapters/postgres/frontier.py`) reserve a seq and insert on the
  connection they already hold — the row is already locked by the
  transition, so the reservation costs nothing. The guard that makes the
  transition honest makes the event honest: **a `run_state` row exists iff
  the transition happened.** A caller-side emit could crash between
  transition-commit and event-insert and lose the terminal event for ever —
  the one event a reconnecting client cannot live without. This also answers
  "who emits for a run finished by `finish_drained`, which no worker owns":
  **the transition does** — `_FINISH_DRAINED` already returns the runs it
  finished; the adapter emits per returned row in the same transaction.
- **`page`, `progress`, `domain_state` are emitted by the worker after the
  durable write they project** (observation/queue-close/domain row), each in
  its own short transaction. Losing one to a crash is acceptable: the rows
  are the facts, events are the SSE projection. No coupling to the queue
  transaction — the observation path must not hold locks while writing a
  different table.

The mechanism is uniform: `emit` always does reserve-then-insert on whatever
connection it is given; transitions pass their open connection, the worker
path opens its own.

### 3. The emission set and volume

| kind           | emits when                                                                                                                                                                                                                                                             | call site                                                                                    | payload                                                                                                                                                                                                                                                                                       |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `page`         | a queue row closes `done` **or final `failed`** (after `MAX_ATTEMPTS`, a 403, robots-disallow). Not on retry-`pending`, not on `release`, not on `abandoned`                                                                                                           | `crawl.py` `_close`, after `complete()` returns True and the target state is `done`/`failed` | `{url, status, strategy, fields, ok}` — spec 005 §3's keys. `status` = the fetched HTTP status, `null` when no request was made (robots, fetch-failed); `strategy` = the observation's strategy, `null` when none; `fields` = count of normalised fields; `ok` = the row closed `done`        |
| `progress`     | after each page close that moved a domain's counts, **throttled to at most one per (run, domain) per second** (in-process, monotonic clock, held by the crawler)                                                                                                       | `crawl.py`, beside the page event                                                            | `{domain, queued, in_flight, done, failed, depth}` — spec 005 §3's keys plus spec 002 §7's `depth` = the depth of the page whose close triggered the event. Counts are one grouped `SELECT state, count(*)` on `crawl_queue` for the (run, domain) — the frontier's table; add the read there |
| `domain_state` | a domain actually moved: the three-403 pause; the 1.11 `BREAK`/`NEVER_MATCHED` halts                                                                                                                                                                                   | `crawl.py` `_pause_if_blocked` (`moved is not None`) and `_observe`'s halted branch          | `{domain, state, reason}` — spec 005 §3's keys; `reason` = `three_403s` \| `break` \| `never_matched`                                                                                                                                                                                         |
| `run_state`    | every run transition: pause, resume, stop, cap-halt, both finishes                                                                                                                                                                                                     | inside the transition transactions (§2)                                                      | `{state, stop_reason?, stats?}` — spec 005 §3's shape; `stats` on terminal transitions (the transition-time snapshot, the same one 2.5/2.7 write to `runs.stats`); `stop_reason` when set                                                                                                     |
| `asset`        | **not emitted until 5.2.** Nothing drains `asset_queue`; the only honest payload today is a queue-depth gauge, which is live state 3.6 can query directly, not history a reconnect needs replayed; download/dedupe events do not exist until 5.2. Pinned, not invented | —                                                                                            | —                                                                                                                                                                                                                                                                                             |

**Why `abandoned` rows emit no page event:** a stop or cap breach abandons
up to the whole remaining queue at once — thousands of events in one burst is
exactly what spec 005 §3's coalescing line forbids; the `run_state` event's
`stats.pages_abandoned` carries the number. Same reasoning for retry-`pending`
(a retry is not an outcome) and `release` (backpressure, nothing happened).

**Volume discipline (spec 009):** events are rows, not log lines. Emission
adds no log line above `debug` — 1.13's line budget is untouched, and the
1,000-page budget test must stay green. Growth is bounded by page rate plus
≤1/s/domain from progress; the 5,000-per-run bound (§4) is what keeps the
table honest past that.

**Throttle scope, stated:** the throttle is per worker process; two replicas
emit at most 2/s/domain. Spec 005 §3 states the one-per-second coalescing for
the endpoint — 3.6 can coalesce further on read. Flagged in Open questions.

### 4. The trim — keep-last-5,000, in the existing sweep beat

`PostgresRunEvents.trim()` is called from the claim loop's `_next()` in
`pools.py`, immediately after `sweep_expired_leases()` — the maintenance beat
the human named. One set-based statement, **live runs only**:

```sql
DELETE FROM crawl.run_events e
USING (SELECT e2.run_id, max(e2.seq) AS hi
       FROM crawl.run_events e2
       JOIN crawl.runs r ON r.id = e2.run_id
          AND r.state IN ('running', 'paused')
       GROUP BY e2.run_id) m
WHERE e.run_id = m.run_id AND e.seq <= m.hi - :keep
```

- **Why per-iteration is cheap enough:** the candidate set is the live runs
  (a handful); per run it is one backward probe on `ix_run_events_run_seq`;
  a run under the bound deletes nothing. The cost is probes, not scans, and
  the loop already pays a sweep per iteration. 15 loops probing a handful of
  runs a few times a second is noise beside the claim itself.
- **Terminal runs are frozen** — nothing emits for them — so restricting the
  sweep to `running|paused` loses nothing. A terminal run therefore retains
  at most 5,000 + ε, where ε = the events between the last sweep trim and
  termination (bounded by one trim interval's emissions). The ε is
  documented slop on a knob the user has already marked "tuned later";
  folding a one-shot trim into every terminal transition (five call sites)
  was rejected as exactness nobody needs at that price. The `run_state`
  terminal event is always retained — it is the newest row.
- **The 7-day post-run purge (spec 005 §3) is retention, not bounding, and
  is not this slice** — nothing consumes events before 3.6; that purge
  belongs to 3.6/5.11's sweep.
- **SSE backfill semantics, pinned in one sentence for 3.6:** a reconnect
  whose `Last-Event-ID` is below the oldest retained seq is backfilled with
  the entire retained window, and because `seq` is gap-free the truncation is
  detectable by arithmetic — first delivered `id:` > `Last-Event-ID + 1` —
  with no protocol change and no synthetic marker event.

### 5. Writer shape — one adapter, adapter-direct, no port

New file `backend/spydra/adapters/postgres/run_events.py`:

- `class PostgresRunEvents(engine)` — `async emit(run_id, kind, payload) ->
int` (the seq), own transaction: reserve + insert; and
  `async trim(keep = 5_000) -> int` (rows deleted).
- module-level `async def emit_in(conn, run_id, kind, payload) -> int` — the
  same two statements on a caller's open transaction (used by `runs.py` and
  `frontier.py` transitions).
- **No `emit_many`:** no call site emits more than one event at a time. A
  per-batch reservation (`next_seq = next_seq + :n`, spend `n-k+1..n`) is the
  one-line upgrade if a batching call site ever appears; noted, not built.
- **Adapter-direct, no `ports/` entry**, following 2.7's precedent and the
  codebase's own shape: the worker already consumes `PostgresRuns` and the
  other repositories directly — Frontier is a port because it is the
  reversible-Postgres decision (ADR-0002/0008), not because everything the
  worker touches is a port. A one-implementation port is an untested
  abstraction.

Payload schemas are JSONB and pinned in §3's table — spec-named keys only,
nothing speculative: 3.16's monitor reads `progress.depth` and
`run_state.stats`; 3.6 replays rows as-is.

### 6. ADR-0042 — required

2.5 needed an ADR to add one terminal path; this slice picks a concurrency
mechanism with named losers, fixes SSE reconnect semantics (gap-free), sets
the bounded-log policy ADR-0012 called "a real piece of work", and splits
emission into transactional-vs-projected. **Number 0042**, file written by
backend, content decided here:

- Title shape: _"Monotonic per-run event sequence from a counter column"_
  (relates-to 0002, 0012, 0040, 0041).
- Decision: the counter reservation (and why not max/retry/lock/advisory/
  batch); gap-free and what it buys SSE; the 5,000 bound, the live-runs-only
  trim shape and its ε; transactional `run_state` vs projected page/progress/
  domain_state; the emission set table incl. `asset` deferred to 5.2 and why
  abandoned/retry/release emit nothing; adapter-direct, no port.
- Alternatives: §1's four losers; the terminal-transition trim (ε exactness);
  a `run_events` port; unthrottled progress (the burst argument).

## Files this slice owns

Production:

- `backend/spydra/adapters/postgres/run_events.py` — NEW (adapter + SQL +
  trim)
- `backend/spydra/adapters/postgres/runs.py` — in-transaction `run_state`
  emission on pause/resume/stop/`finish_if_drained`/`finish_drained`
- `backend/spydra/adapters/postgres/frontier.py` — `halt_run`'s in-transaction
  `run_state` emission; the `queue_counts` read for progress payloads
- `backend/spydra/adapters/postgres/tables.py` — `runs.next_seq` Core mirror
  (2.5's precedent, or the next autogenerate drops it)
- `backend/spydra/scheduler/crawl.py` — page + domain_state emission, the
  progress throttle
- `backend/spydra/scheduler/pools.py` — the trim hook in `_next()`, adapter
  wiring
- `backend/migrations/versions/<new>_runs_next_seq.py` — NEW (column +
  backfill; up/down)
- `docs/adr/0042-*.md` + `docs/adr/README.md` — NEW (backend writes from §6;
  filename may tighten, number may not)
- `docs/specs/001-domain-model.md` — §1 runs DDL gains the `next_seq`
  late-column comment; the `run_events` block notes the kinds emitted and the
  bound
- `docs/specs/002-scheduler.md` — §7 gains the progress cadence line
  (throttle, depth source)
- `.tasks/feat-2.8-run-events.md` — this file

Tests (test agent owns; extend rather than multiply where a file exists):

- `backend/tests/adapters/postgres/test_run_events.py` — NEW: the two-engine
  seq race, gap-free/monotonic, trim bound, `emit_in` transactionality,
  payload shapes per kind
- `backend/tests/adapters/postgres/test_run_lifecycle.py` — extend: every
  transition writes its `run_state` row (and only the transitioning call
  does)
- `backend/tests/scheduler/test_run_control.py` / `test_trap_crawls.py` /
  `test_worker_process.py` — the real-worker seam events (cap-halted
  `run_state`, stopped `run_state`, page/progress/domain_state emission, the
  line budget still green)
- `bff/src/db/schema/crawl.generated.ts` — regenerated via `make generated`,
  never hand-edited

**`backend/spydra/api/` is untouched** — 3.6 builds the endpoint; this slice
has no consumer and adds none.

## Acceptance (from BUILD_PLAN 2.8's done-when)

- [ ] Two real engines emitting concurrently into one run: `UNIQUE (run_id,
    seq)` holds, every insert lands with its own seq — N concurrent emits
      yield N rows, seqs exactly `1..N`, none dropped, none duplicated
- [ ] `seq` is monotonic per run and **gap-free** (pinned): a rolled-back
      emission reserves nothing; a killed worker's in-flight transaction
      leaves no hole
- [ ] The trim holds the bound on a run that emits past it: a run emitting
      5,000 + k events retains ≤ 5,000 while running, and the `run_state`
      terminal row is always among them
- [ ] The 2.5 seam replays: a cap-halted run has its `run_state` row —
      `failed`, the `stop_reason`, transition-time `stats`
- [ ] The 2.7 seams replay: a stopped run (and a paused, and a resumed run)
      each have their `run_state` rows; every completion path — a worker's
      last close, the sweep's `finish_drained`, resume's drained finish —
      writes its `completed` `run_state` row even though no worker owns the
      run in the last two
- [ ] `domain_state` rows for the three-403 pause and the 1.11 halts;
      `page` rows on `done` and final-`failed` closures only (none on
      retry/release/abandon); `progress` rows carry `depth` and are throttled
      to ≥ 1 s per (run, domain)
- [ ] No `asset` rows (pinned until 5.2)
- [ ] Spec 009 discipline: a 1,000-page run still meets the line budget —
      emission adds no log line above `debug`
- [ ] Migration up/down/up; `make generated` clean (`next_seq` reaches
      `crawl.generated.ts`); `make check` green

## Handoff log

- planner — contract above; branch cut from `feat/2.7-run-lifecycle`
  @ `616bb83`. Two spec notes recorded: spec 005 §3's example says
  `event: assets` where spec 001's DDL kind is `'asset'` — the DDL is the
  writer's vocabulary, the plural is 3.6's problem; and 1.13 OQ6
  (`stats.by_domain` refusal counts) is now answerable from page events by
  3.16 rather than by widening `stats` — not re-opened here. **Hand off to
  spydra-backend — first file
  `backend/spydra/adapters/postgres/run_events.py`** (the migration and the
  transitions' emission follow; ADR-0042 is backend's to write from §6).

## Open questions

- none blocking. Flagged for the human (planner decisions taken, reversible
  cheaply): the progress throttle is per worker process, so two replicas
  emit up to 2/s/domain (3.6 can coalesce on read); the terminal-run trim
  slop ε (≤ one trim interval) vs folding a one-shot trim into all five
  terminal transitions — rejected as exactness nobody needs; the 7-day
  post-run purge from spec 005 §3 is deliberately not here (nothing consumes
  events until 3.6); `page.fields` is a count of normalised fields, matching
  spec 005 §3's `"fields":7`.
