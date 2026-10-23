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

- [x] Two real engines emitting concurrently into one run: `UNIQUE (run_id,
seq)` holds, every insert lands with its own seq — N concurrent emits
      yield N rows, seqs exactly `1..N`, none dropped, none duplicated
      (`test_run_events.py` §1: blocked-behind-uncommitted-reserve, 30
      alternating rounds, 40-emit burst)
- [x] `seq` is monotonic per run and **gap-free** (pinned): a rolled-back
      emission reserves nothing; a killed worker's in-flight transaction
      leaves no hole (rollback discards reservation and insert together —
      `test_a_rolled_back_emission_reserves_nothing_and_leaves_no_hole`,
      and the transition probe
      `test_a_rolled_back_transition_leaves_neither_state_nor_event`)
- [x] The trim holds the bound on a run that emits past it: a run emitting
      5,000 + k events retains ≤ 5,000 while running, and the `run_state`
      terminal row is always among them (exactly `KEEP_EVENTS` retained,
      first seq `hi - keep + 1` — the off-by-one pinned both edges)
- [x] The 2.5 seam replays: a cap-halted run has its `run_state` row —
      `failed`, the `stop_reason`, transition-time `stats`
      (`test_trap_crawls.py`, extended)
- [x] The 2.7 seams replay: a stopped run (and a paused, and a resumed run)
      each have their `run_state` rows; every completion path — a worker's
      last close, the sweep's `finish_drained`, resume's drained finish —
      writes its `completed` `run_state` row even though no worker owns the
      run in the last two (`test_run_lifecycle.py` §9 at the adapter,
      `test_run_control.py` through the live worker, the sweep's
      unowned-finish case extended in `test_page_crawler.py`)
- [x] `domain_state` rows for the three-403 pause and the 1.11 halts;
      `page` rows on `done` and final-`failed` closures only (none on
      retry/release/abandon); `progress` rows carry `depth` and are throttled
      to ≥ 1 s per (run, domain) (`test_page_crawler.py`'s emission-set
      section; the throttle crosses the window with a real 1.1 s sleep on
      the crawler's own monotonic clock)
- [x] No `asset` rows (pinned until 5.2) — the volume test's kind set is
      capped at `{page, progress, domain_state, run_state}` and asserts no
      `asset`
- [x] Spec 009 discipline: a 1,000-page run still meets the line budget —
      emission adds no log line above `debug` (1.13's budget tests green
      and untouched; the volume test additionally asserts the info log
      names no emission)
- [x] Migration up/down/up; `make generated` clean (`next_seq` reaches
      `crawl.generated.ts`); `make check` green — migration and generated
      were backend's (proven down/up on the test DB per its handoff);
      `make lint` and `make test-api` green from the test side

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
- backend (2.8) — implemented as pinned, all seven items. Built:
  `run_events.py` (adapter `emit`/`trim` + module `emit_in`, reserve-by-
  UPDATE-RETURNING + INSERT, `KEEP_EVENTS = 5_000` as `trim`'s default,
  no `emit_many`); migration `f4b2d6a91c03_runs_next_seq` (column +
  backfill, down = drop column; proven down/up on the test DB);
  `run_state` inside every transition transaction — `runs.py`
  pause/resume/stop/`finish_if_drained` (via new `_finish_if_drained_in`
  helper, shared with resume's drained finish)/`finish_drained` (per
  returned row), `frontier.py` `halt_run` (its statement now `RETURNING
id, stats` so the event carries the transition-time snapshot); worker
  emission in `crawl.py` — `page` on done/final-failed closes only via
  `_close`'s new `_PageOutcome` param, `progress` throttled 1/s/(run,
  domain) on the monotonic clock carrying `item.depth` (counts from new
  `PostgresFrontier.queue_counts`), `domain_state` on `_pause_if_blocked`
  (`moved is not None`) and `_observe`'s halted branch; the trim called
  from `ClaimLoop._next()` beside the sweep; ADR-0042 + README index;
  spec 001 (runs DDL late column + run_events kinds/bound note), spec 002
  §7 (cadence line). No log lines added or changed.
  **Deviations/findings for the test agent:**
  1. `Repositories` and `ClaimLoop` gained a required `events=` keyword —
     the two `build()` fixtures (`test_page_crawler.py:153`,
     `test_canonical_pages.py:79`) and the two `ClaimLoop` constructions
     (`test_page_crawler.py:769,804`) need `events=PostgresRunEvents(engine)`.
     These four sites are the ONLY remaining failures: 45 failed / 1114
     passed, every failure the constructor TypeError, zero behavioral
     assertion failures. 2.7's transition tests and runctl pass unchanged.
  2. One file beyond the declared list: `ports/frontier.py` gained an
     8-line `queue_counts` Protocol method. The pin placed the read on the
     frontier (the queue's owner) while `PageCrawler` holds the frontier
     through the port — a cast or a second concrete collaborator were the
     only alternatives, both worse. Flagged here per the ownership rule.
  3. `_HALT_RUN` now returns `(id, stats)` instead of `id` — internal to
     the adapter; `RunHalt`'s shape is unchanged.
  4. `crawl.generated.ts` regenerated (next_seq reached it, line 243) —
     dev DB migrated first (`make migrate`), since drizzle introspects the
     live database.
- test (2.8) — suite 1184 passed / 2 skipped / 1 xfailed (the defect below)
  on `make test-api`; `make lint` green. **Fixture repairs first, own
  commit:** the four sites the backend's handoff named now pass
  `events=PostgresRunEvents(engine)` exactly as `worker.py` wires it (both
  `build()`s and both `ClaimLoop`s) — the real adapter over the real test
  engine, keeping every existing assertion honest. Suite green at that
  point: 1159 passed.
  **New `backend/tests/adapters/postgres/test_run_events.py`** (13 tests):
  the two-engine race (blocked-behind-uncommitted-reserve → 30 alternating
  commits → 40-emit burst = seqs exactly `1..102`), rollback discards
  reservation and insert together (gap-free), the transition-rollback probe
  (neither state nor event nor `next_seq` survives), JSONB payload
  roundtrip, the trim at the shipped constant (exactly `KEEP_EVENTS`
  retained, both edges), below-bound no-op, `running|paused` both swept,
  terminal runs frozen in all three states, the ε between trims bounded by
  emission, and the SSE truncation-detection arithmetic (`first > id+1`
  ⇒ truncated, in-window ⇒ contiguous). **`test_run_lifecycle.py` §9:**
  pause/resume/stop each write their `run_state` row with spec-005 shapes
  (a fenced re-pause emits nothing), resume's drained finish writes
  `running`+`completed` in one transaction, `finish_drained` writes the
  unowned `completed` per run, `halt_run` writes `failed` with reason and
  post-abandon stats. **`test_page_crawler.py`:** the emission set — done
  close (`page` + `progress` with the exact key sets and real values, then
  the finish's `run_state`), 403 close (`page` with the refusal's shape),
  retry and release emit nothing (burst guard's negative space, both on one
  run), the throttle on the real monotonic clock (two closes in-window →
  one progress; a real 1.1 s sleep → two; three pages → three `page`s),
  depth carried, the three-403 `domain_state`, the BREAK `domain_state`,
  and the sweep-finish test extended with its unowned `completed` event.
  **`test_run_control.py` / `test_trap_crawls.py`:** the live-worker seams
  — stop/pause/resume/replay assertions on the real sequences, the
  cap-halt's `failed` row with the reason and the abandoned count, no
  `page` event for any abandoned row (stop and halt both), and the volume
  test (Halden through the real process: `page` == closed rows, `progress`
  ≤ elapsed+2 and < pages, kind set ⊆ the four, no `asset`, terminal
  `run_state` newest, no emission line in the info log).
  **Mutations — each red, restored, green:** counter increment removed
  (`UniqueViolationError` on the second emit — the pinned no-retry design
  fails loudly, no silent retry); trim live-runs filter dropped (terminal
  tail deleted in all three states); trim `<=` → `<` (19 ≠ 20 — the
  off-by-one); throttle window removed (progress per close); `page` event
  added to the release path (caught by the burst guard's negative space);
  `finish_drained`'s emission removed (unowned finish goes silent); depth
  dropped from `progress` (key-set pin). "run_state moved out of the
  transition transaction" is not observable without fault injection — the
  crash window it opens is exactly what the rollback probe pins at the
  mechanism level instead.
  **Production defect found — red test pinned as `xfail(strict)`, not
  fixed** (`test_page_crawler.py::
test_the_never_matched_halt_names_the_state_the_domain_moved_to`):
  `crawl.py`'s halted branch hard-codes `"state": "broken"` for every halt,
  but `NEVER_MATCHED` moves the domain to `awaiting_approval`
  (`domain/lifecycle.py`), so the event names a state the domain is not in.
  The handoff comment's claim ("both move the domain to `broken`") is
  wrong for `never_matched`. The three-403 event reports the actual moved
  state (`moved.value`); the halted branch should do the same. Proven:
  XFAIL(strict) today with the precise diff (`broken` vs
  `awaiting_approval`), XPASS(strict) under the aimed fix — fixing the
  production line will turn the suite red until the marker is removed.
- backend (2.8, defect fix) — fixed the pinned defect: the halted branch
  now emits `transition(DomainState.ACTIVE, outcome.event).value` — the
  same pure lifecycle function the writer's own move used. Both halt edges
  exist only from `active` (`_EDGES`), so this is exactly the state the
  verdict moved the domain to: `broken` for BREAK, `awaiting_approval`
  for NEVER_MATCHED (ADR-0030). One site changed, no API reshaping;
  `make lint` green; the pinned test XPASSes — **suite shows 1 "failed" =
  that XPASS(strict) until the test agent removes the marker
  (test_page_crawler.py:1092); the next runner should expect exactly that
  one red, not a regression.**
  **Reviewer note:** one test-data subtlety — `observation_seed.
seed_observation` writes no `template_id`, and the health sample counts
  only observations a product template made, so the never_matched fixture
  pins the template on its seeded rows (the BREAK fixture is unaffected:
  regressions read the prior's `content_hash`, not its template).
- test (2.8, follow-up) — the halt-state defect above **fixed by backend
  `01b529b`** (the event now computes `transition(ACTIVE, verdict).value`);
  the `xfail(strict)` marker removed and the test asserts for real — 1185
  passed / 2 skipped / **0 xfailed**. Both edges now pinned in both forms:
  `NEVER_MATCHED` → `awaiting_approval` against the domain row itself, and
  the BREAK edge gained the same domain-row oracle beside its literal
  `broken` payload.

## Open questions

- none blocking. Flagged for the human (planner decisions taken, reversible
  cheaply): the progress throttle is per worker process, so two replicas
  emit up to 2/s/domain (3.6 can coalesce on read); the terminal-run trim
  slop ε (≤ one trim interval) vs folding a one-shot trim into all five
  terminal transitions — rejected as exactness nobody needs; the 7-day
  post-run purge from spec 005 §3 is deliberately not here (nothing consumes
  events until 3.6); `page.fields` is a count of normalised fields, matching
  spec 005 §3's `"fields":7`.
