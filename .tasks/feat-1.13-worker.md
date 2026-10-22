# feat/1.13-worker

**Task:** BUILD_PLAN 1.13 · **Spec:** 002 §1–§7, 009 §1/§5, 012 §4
**ADRs that constrain this:** 0002, 0003, 0004, 0016, 0023, 0026 (amended by
0034, written here), 0027, 0030, 0033

Stacked on `fix/1.11-review-findings`, which is stacked on #17.

## Contract

`python -m spydra.worker` is the worker service. It runs:

- the **static pool**: 12 claim loops (`WORKER_STATIC`). These claim
  domains whose `render_mode` is `static` or `auto`.
- the **rendered pool**: 3 claim loops (`WORKER_RENDERED`). These claim
  `rendered` domains only.
- both pools in **one `asyncio.TaskGroup` over one engine** (one connection
  pool, ADR-0003). Every call to the sidecar takes a slot in one shared
  `RenderBudget` semaphore, sized like the rendered pool, so an AUTO second
  chance issued from the static pool cannot oversubscribe the sidecar
  (1.7 open question 4).
- **no asset pool.** Nothing drains `asset_queue` until 5.2 (BUILD_PLAN 1.12
  says building it now is building it for no consumer). The third pool
  arrives with its consumer. Raised below.

One claim-loop iteration (spec 002 §1–§7):

1. `sweep_expired_leases()`. This is load-bearing since ADR-0026.
2. `AssetPressure.before_claim(pending)`.
3. `claim(render_modes)`.
   - `None` means **nothing is claimable right now, not "the frontier is
     empty"**. The loop idles (0.5 s) and goes round again; the worker runs
     until SIGTERM.
4. Crawl the claimed URL (`PageCrawler`):
   - **domain:** load the domain row (politeness state, render mode, user
     agent, robots flag, configured delay).
   - **robots:** check `robots.txt`, cached per run. A disallowed URL closes
     the row as `failed`, with no fetch and no politeness change.
   - **fetch** by render mode:
     - `rendered`: through the sidecar.
     - `auto`: static first. On a 200 whose chain result is **not
       substantive**, `fetch_rendered_or_fall_back` with the page already in
       hand, under the `RenderBudget`. "Not substantive" is spec 012 §4's
       "nothing usable", and it is deliberately wider than
       `empty_extraction`: a server-HTML SEO stub carrying only an image
       must not stop a JS-dependent page from getting its browser retry
       (`fix/1.11-review-findings` open question 12).
   - **outcome:**

     | Outcome                          | Action                                                                                                                    |
     | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
     | `Backpressure`                   | `release` the row (no penalty)                                                                                            |
     | `FetchFailed`                    | `on_fetch_error`; retried until 3 attempts, then `failed` plus `unknown_pages(fetch_error)` (closes 1.11 non-blocking 6e) |
     | HTTP response                    | `gate.for_status`; see the next row                                                                                       |
     | 2xx, or a 4xx other than 403/429 | upsert `pages`, match the template, run the chain, `ObservationWriter.record`, row `done`                                 |
     | 429/503/5xx                      | retried until 3 attempts, then `failed`; no observation                                                                   |
     | 403                              | row `failed`, never retried; three in a row pause the domain via `BLOCK` and abandon its queue (ADR-0004)                 |

   - **halt:** when the writer halts the domain (`BREAK`/`NEVER_MATCHED`),
     abandon its remaining rows so the run can finish.
   - **finish:** if the run has no `pending`/`in_flight` rows left, mark it
     `completed` with `finished_at` and `stats` (spec 009 §5: stats on
     completion). The statement is one guarded `UPDATE`, so a run finishes
     once.
5. On SIGTERM:
   - stop claiming;
   - give in-flight pages `SHUTDOWN_GRACE_S` (20 s) to finish;
   - cancel what remains and `release` its rows (no penalty, `in_flight`
     given back);
   - close both fetchers and the engine;
   - exit 0.

   `compose.yaml` gets `stop_grace_period: 30s` so Docker does not SIGKILL
   inside the grace.

### Two defects this slice has to fix to work at all

- **The claim starves.** ADR-0026's `eligible` CTE picks the most eligible
  `active` domain without asking whether it has a pending row.
  - A domain whose queue is drained is never fetched again, so its
    `next_eligible_at` never advances and it stays the most eligible domain
    for good.
  - Every other domain then gets `None` for ever. That is permanent
    starvation, not "occasionally a wasted claim" as 1.12 described it.
  - Fix: `AND EXISTS (pending row of d)` plus the pool's `render_mode`
    filter, both inside `eligible`.
  - Both locks are unchanged. **ADR-0034** records the amendment, and spec
    002 §1's SQL is updated.
- **Spec 002 §4's decay has no floor** (1.9 open question 1).
  - Add `domains.configured_crawl_delay_ms` (default 2000).
  - The worker passes `floor_ms = max(configured, robots Crawl-delay)`.
  - Without it, the backoff permanently replaces what the operator set.
    Without it the acceptance run could not go faster than 2 s per page
    either.

### Logging (spec 009 §1, §5)

- `structlog`, JSON to stdout. It is named in AGENTS.md § Stack and spec 009
  §1, and is pure Python, so it is not a new decision and there is no wheel
  risk.
- Stdlib `logging` records (politeness, robots) go through the same
  renderer.
- Every crawl-path line carries `run_id`, `domain`, `url`, `strategy`,
  `attempt`.
- Levels:

  | Level     | Events                                                        |
  | --------- | ------------------------------------------------------------- |
  | `info`    | worker started and stopped, run finished, domain state change |
  | `warning` | backoff, 403, a retry that ran out, robots override           |
  | `debug`   | per page                                                      |

- No body, header or credential is ever passed to a log call.

## Files this slice owns

- backend/spydra/worker.py (new; the entry point)
- backend/spydra/scheduler/{crawl,pools}.py (new)
- backend/spydra/logs.py (new; structlog configuration)
- backend/spydra/adapters/postgres/{domains,pages,templates,runs}.py (new)
- backend/spydra/adapters/postgres/frontier.py, ports/frontier.py (claim filter)
- backend/spydra/adapters/postgres/tables.py + one migration (`configured_crawl_delay_ms`)
- backend/spydra/domain/enums.py (`UnknownReason.FETCH_ERROR`)
- backend/pyproject.toml, backend/uv.lock (structlog)
- backend/tests/fixtures/server.py (a generated 1,000-product catalogue route)
- compose.yaml (worker command, stop grace)
- docs/specs/002-scheduler.md §1, docs/specs/001-domain-model.md §1,
  docs/adr/0034-*.md
- backend/tests/** (test-writer)
- bff/src/db/schema/crawl.generated.ts (regenerated)

## Acceptance

- [ ] The worker crawls the fixture site's seeded URLs to completion against
      real Postgres and real fetchers: rows `done`, observations written,
      assets enqueued, run `completed` with `stats`.
- [ ] A second `active` domain with an empty queue does not starve the
      first (fails on the 1.12 claim).
- [ ] A static-pool loop never claims a `rendered` domain, and vice versa.
- [ ] SIGTERM mid-run: the process exits 0 within the grace, and no row is
      left `in_flight` with `in_flight` counters at 0.
- [ ] A 1,000-page run at `info` writes fewer than 100 lines, and no line
      contains an HTML body, a `<` tag or a credential (spec 009 §5).
- [ ] `FetchFailed` three times gives `failed` plus an
      `unknown_pages(fetch_error)` row.
- [ ] Three 403s pause the domain and abandon its rows.
- [ ] A 503 from the sidecar releases the row with no attempt charged.
- [ ] The decay never goes below `configured_crawl_delay_ms`.
- [ ] `make check` green; migration up/down/up; mutation run, each guard red.

## Handoff log

- planner: contract above.
- backend: as contracted, with these deviations:
  - **`MAX_ATTEMPTS` moved to the port**, so the scheduler decides
    retry-or-fail without importing an adapter. The adapter re-exports it.
  - **`RobotsRules.can_fetch` compared a hostname with a host that may carry
    a port**, so a domain at `127.0.0.1:PORT` had every URL refused as
    foreign. It now compares hostname with hostname. Found running the
    worker.
  - **The `httpcore2` logger wrote raw response headers at `debug`**
    (including `Set-Cookie`, a credential). It is now held at `warning`.
    Found running the worker at `debug`.
  - **Smoke run** (throwaway, not committed): the real worker as a
    subprocess against `FixtureSite` and the test DB, with 5 URLs.
    - All 5 rows `done`. The product gives selector, title and £14.75. The
      listing gives `empty_extraction`, the two unmatched pages
      `no_template`, the 404 an observation and no inbox row.
    - Run `completed` with stats, `in_flight` back to 0, SIGTERM exit 0.
    - 3 lines at `info`; at `debug`, one per page plus lifecycle.

## Open questions — for the human

Carried: the eleven from `fix/1.11-review-findings` and earlier.

New:

1. **No asset pool until 5.2.** ADR-0003 and spec 002 §6 say three pools;
   this ships two and leaves the third to arrive with its consumer.
2. **The robots fetch is still outside the gate** (1.9 open question 2). The
   first page of a domain follows its `robots.txt` back to back. Unchanged
   here.
3. **Which template wins when several active templates match** is
   unspecified. This takes the lowest id. Spec 001 §1 only forbids two
   active templates with the same pattern.
4. **Observations are written for 4xx (404, 410) but not for 403/429/5xx.**
   A dead link is a fact about the page. A refusal or an outage is a fact
   about the request.
