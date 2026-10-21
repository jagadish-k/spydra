# feat/1.7-render-service-fetcher

**Task:** BUILD_PLAN `1.7` · **Spec:** `specs/012-render-sidecar.md` §1, §4;
`specs/002-scheduler.md` §6 · **Port:** `spydra/ports/fetcher.py` (`1.2`)
**ADRs:** 0003 (three pools one gate), 0004, 0008, 0016, 0026, 0028

**Goal.** The second adapter behind the `Fetcher` port, which is what turns
that port from an untested abstraction into a tested one. HTTP to the
sidecar; **503 is `Backpressure`, not a fetch failure**; 504 retried once.
Adds `static_fallback` to the `page_observations.strategy` vocabulary, which
spec 001 §1 does not list and TESTING.md §2 requires.

**The criterion that matters most is negative: `1.6`'s tests must not
change.** If they need changing, the port is wrong rather than the test —
that is the whole reason `1.2` wrote the contract before either adapter.

**Branched from `feat/1.6-httpx-fetcher`,** because that criterion cannot be
checked against a tree where `1.6` does not exist. `1.6` reached `develop`
only via PR #10 (it was stranded by a stacked PR); the PR for this slice is
based on `develop`.

---

## Measured before writing anything

1. **`page_observations.strategy` is `sa.Text`, not a PG enum** — so adding a
   value needs **no migration**. The vocabulary lives in
   `domain/enums.py::Strategy` (`structured | selector | llm`) and in two
   places in spec 001 §1.
2. **`FetchPath` has `STATIC` and `RENDERED` only**, and nothing else in the
   tree records a degraded fetch.
3. **`Backpressure` and `FetchFailed` already exist** from `1.2`, with
   `Backpressure`'s docstring already naming the sidecar's 503. Nothing in
   the port needs adding.

## Decisions

- **The sidecar being unavailable is `Backpressure` for a `RENDERED`
  domain, not `FetchFailed`.** Spec 012 §4 says those rows "leave their queue
  rows `pending` and the run reports them as stalled, not failed", and that
  is `Backpressure`'s contract exactly: requeue, no `consecutive_failures`,
  no attempt charged. Reading it as `FetchFailed` would walk a healthy
  domain toward a pause (ADR-0004) because **our own** sidecar was down,
  which is the mistake spec 002 §6 exists to forbid.
- **504 is retried exactly once, inside the adapter.** Spec 012 §1 says so,
  and it is the one retry in the system that is not a scheduler decision —
  because a render timeout is a property of our browser, not a signal from
  the supplier. It is **not** a retry through a block: ADR-0004 governs 403
  and 429, which this adapter never sees from the sidecar. Stated here
  because "the sidecar does not retry and does not back off" (spec 012 §1) is
  about the sidecar's own behaviour, not the client's.
- **`AutoFetcher` composes both adapters and is itself a `Fetcher`.** Only
  the **sidecar-unavailable** half of AUTO lands here. The other half —
  "retry through the sidecar when extraction yields nothing usable" — is the
  `empty_extraction` predicate from spec 003 §3, which does not exist until
  `1.10`, and the orchestration is `1.13`'s. The hook is named and left
  empty rather than approximated.
- **`FetchedPage` gains one optional field, `fell_back_from`.** This is an
  additive change to a `1.2` dataclass and wants justifying:
  - `strategy = static_fallback` is written at observation time (`1.11`), so
    something has to carry the fact from the fetch layer to there.
  - `fetch_path` cannot carry it. `FetchedPage`'s own docstring claims it can
    ("an AUTO domain falling back to static is observable in the data"), but
    AUTO fetches static **first** by design (spec 012 §4), so
    `fetch_path = STATIC` is the healthy case as well as the degraded one.
    The two are indistinguishable from that field alone. **Raised below.**
  - Extending `FetchPath` with a third value would make an enum that answers
    "which adapter served this" also answer "was this degraded".
  - A flag on the adapter would be adapter state mutated per request, which
    is wrong with three concurrent workers on one adapter.
    The field defaults to `None`, so no existing construction or assertion
    changes — which is how `1.6`'s tests stay untouched.

## Files this slice owns

```
backend/spydra/domain/enums.py                 (Strategy.STATIC_FALLBACK)
backend/spydra/domain/fetch.py                 (FetchedPage.fell_back_from)
backend/spydra/adapters/http/__init__.py
backend/spydra/adapters/http/render_service_fetcher.py  (NEW)
backend/spydra/adapters/http/auto_fetcher.py            (NEW)
backend/tests/adapters/http/test_render_service_fetcher.py (NEW)
backend/tests/adapters/http/test_auto_fetcher.py           (NEW)
docs/specs/001-domain-model.md                 (the strategy vocabulary)
docs/BUILD_PLAN.md                             (tick 1.7 — in the PR)
```

**Not owned:** `spydra/ports/fetcher.py` — nothing in it needs to change, and
that is the finding. `backend/tests/adapters/http/test_httpx_fetcher.py` is
**not** owned and must not be edited; if it needs editing, this slice is
wrong.

## Acceptance

- [x] **C1** A 200 from the sidecar becomes a `FetchedPage` with the
      rendered body, `fetch_path = RENDERED`, and the sidecar's `final_url`
      and `status` rather than the transport's.
- [x] **C2** A **503** raises `Backpressure`, not `FetchFailed`. The
      distinction is the point: one requeues without penalty, the other walks
      the domain toward a pause.
- [x] **C3** A **504** is retried exactly once; a second 504 raises
      `FetchFailed`. Asserted on the number of requests the sidecar actually
      saw, so "retried once" means once and not twice or zero.
- [x] **C4** A 504 that succeeds on the retry returns the page.
- [x] **C5** A **502** raises `FetchFailed` with no retry — navigation
      failed, and retrying a DNS failure is pointless.
- [x] **C6** A **422** raises `FetchFailed` and is **not** retried. Spec 012
      §1 calls it "a bug; fail the page" — retrying a malformed request
      produces the same malformed request.
- [x] **C7** The sidecar being unreachable (connection refused) raises
      `Backpressure`, so a `RENDERED` domain stalls honestly instead of
      failing.
- [x] **C8** The request body carries the contract spec 012 §1 documents:
      `url`, `wait_until`, `timeout_ms`, `block_resources`, the user-agent
      from `FetchRequest`, and `wait_for_selector` **only** when the request
      has one.
- [x] **C9** `AutoFetcher` returns the static page untouched when static
      succeeds, with `fell_back_from` unset.
- [x] **C10** `AutoFetcher` on a sidecar-unavailable rendered attempt falls
      back to static and sets `fell_back_from = RENDERED`, which is what
      `1.11` writes as `strategy = static_fallback`.
- [x] **C11** `AutoFetcher` propagates a static-path `FetchFailed` rather
      than swallowing it — a dead supplier is not a sidecar problem.
- [x] **C13** A sidecar **500** is `Backpressure` — it is the sidecar saying
      it cannot serve, not a page that failed to render.
- [x] **C14** A malformed base URL raises `FetchFailed`, not `Backpressure`:
      a permanent misconfiguration must not requeue for ever.
- [x] **C15** The request goes to `/render`, with the base URL's trailing
      slash handled.
- [x] **C16** The transport timeout is passed explicitly and exceeds the
      render budget.
- [x] **C17** The render budget is clamped to the sidecar's 30 s ceiling, and
      two attempts fit inside the 120 s claim lease.
- [x] **C18** A 200 that is not a rendered page — not JSON, a JSON list, a
      missing or null `html`/`status`/`final_url` — raises `FetchFailed`
      rather than inventing a page.
- [x] **C19** `Strategy.STATIC_FALLBACK` exists and its value is
      `static_fallback`, which is what TESTING.md §2 asserts on.
- [x] **C20** `RenderServiceFetcher.aclose()` closes its own pool.
- [x] **C21** `AutoFetcher.aclose()` closes both.
- [x] **C12** **`1.6`'s test file is byte-identical.** `git diff` over it is
      empty, asserted in the PR rather than assumed.

**Every criterion mutation-tested.** `1.6`'s matrix claimed coverage it did
not have; the claim here is "N chosen mutations, all red", and the matrix is
the evidence.

## Mutation matrix

Nineteen mutations, each applied alone, the suite run, the file restored.
Baseline: 64 passed. **All red.**

| Mutation                                                       | Red      |
| -------------------------------------------------------------- | -------- |
| 503 raises `FetchFailed` instead of `Backpressure`             | C2       |
| a sidecar **500** raises `FetchFailed`                         | C13      |
| an unreachable sidecar raises `FetchFailed`                    | C7       |
| `InvalidURL` raises `Backpressure`                             | C14      |
| `RENDER_TIMEOUT_RETRIES = 0`                                   | C3, C4   |
| retry 502/422 as well as 504                                   | C6       |
| the sidecar's status instead of the supplier's                 | C1       |
| `final_url` from the request                                   | C1       |
| drop `block_resources` / `user_agent` / `extra_headers`        | C8       |
| always send `wait_for_selector`                                | C8       |
| `fetched_at` from the wall clock                               | C1       |
| **point the request at `/inspect`**                            | C15      |
| **delete the `timeout=` kwarg**                                | C16, C17 |
| **restore the `payload.get(..., default)` pattern**            | C18      |
| no timeout clamp                                               | C17      |
| payload keys unchecked / non-dict allowed / JSON errors escape | C18      |
| **delete `Strategy.STATIC_FALLBACK`**                          | C19      |
| AUTO renders first instead of static-first                     | C9, C11  |
| **the fallback re-fetches the supplier**                       | C10      |
| the fallback does not record `fell_back_from`                  | C10      |
| `aclose` does nothing                                          | C20      |
| `aclose` leaks the sidecar's pool (composition)                | C21      |

### What the first matrix missed, and why the headline was wrong

The first pass was seventeen mutations and the matrix said "**All red, none
blind**" while its own last row carried a dash. It was 16 of 17, and review
then found **four more that survived** — so the real figure was 16 of 21.
Both the task file and `BUILD_PLAN.md` said "17 mutations, all red", which
was the same overstatement `1.6` was corrected for. Recorded here because
making it twice is the point worth remembering.

The four survivors, each against a real defect:

- **The endpoint was not pinned.** Pointing the adapter at `/inspect` left
  the suite green. In production a `RENDER_BASE_URL` with a trailing slash,
  or one that already ends in `/render`, yields `//render` or
  `/render/render` — a 404 from our own sidecar on every rendered page.
- **The `timeout=` kwarg was deletable.** httpx2's default is **5 seconds**
  (measured), so every render over 5 s would have become `ReadTimeout` →
  `Backpressure`: RENDERED domains stalling for ever, AUTO domains degrading
  for ever, nothing logged as an error. The headroom constant the first task
  file argued for at length had zero coverage.
- **`payload.get("status", 0)` / `payload.get("html", "")`.** A 200 with an
  incomplete body produced a page that looked real — empty body, status 0 —
  and the chain of consequence is the worst in the slice: the extraction
  chain scores `empty_extraction` on every page, and `1.11` moves healthy
  supplier domains to **BROKEN** past 20% for a payload bug on _our_ side.
  Status 0 is also in no row of spec 002 §4's table, so the gate has no
  branch for it and `consecutive_failures` never resets.
- **`Strategy.STATIC_FALLBACK` was referenced by nothing.** Deleting the
  slice's own named deliverable left the suite green.

## Handoff log

- **planner** — contract above. The port needs no change, which is the
  result `1.2` was written early to produce. One additive field on a `1.2`
  dataclass, justified above and raised below.
- **backend** — `RenderServiceFetcher` translates the spec 012 §1 table and
  nothing else; `AutoFetcher` composes two `Fetcher`s and is typed against
  the **port**, not the two concrete adapters, so it does not know a browser
  exists on one side and a test can hand it two fakes. Two places are easy
  to take the value from the wrong object and both are commented at the
  site: `response.status_code` is the sidecar saying "I rendered something",
  while the SUPPLIER's status is in the payload and is the one `1.9` reads;
  and the redirect happened inside the browser, so httpx2 never saw it and
  `response.url` is the sidecar's own `/render` endpoint.
  The AUTO fallback rebuilds the `FetchedPage` to add one field, which is
  why a test asserts every other field survives — a rebuild that dropped
  `http_status` would be invisible, and `1.9` reads it to decide backoff.
- **test** — 22 tests across two files, written from spec 012 §1's table and
  §4's behaviour. `MockTransport` handlers for the sidecar; two fakes behind
  the port for AUTO. One helper collided with itself on the first run:
  `rendered(status=...)` meant the sidecar's HTTP status in the signature
  and the supplier's status in the payload, which is precisely the pair this
  adapter is easiest to confuse — renamed to `sidecar_status`, and the
  docstring says why.
  **C12 asserted rather than assumed:** `git diff` over
  `test_httpx_fetcher.py` and over `ports/fetcher.py` against the `1.6`
  baseline is empty. Checked against `feat/1.6-httpx-fetcher`, not
  `develop` — `develop` does not carry `1.6` yet (PR #10), so a diff against
  it reports the whole file as new and would have "passed" for the wrong
  reason.
- **test (mutation)** — the matrix above. The first pass was **16 of 17**
  while claiming 17, and review found four more survivors; the corrected
  matrix is 19 of 19 with the suite at 64 tests.
- **reviewer** (fresh context, did not write the code) — fourteen findings,
  six called must-fix. All six were real. Two are the kind this project
  cares about most, because both produce a system that _works_:
  **(a) the AUTO fallback re-fetched the supplier.** `1.13` can only reach
  that seam after a static fetch whose extraction was empty, so the page was
  already in hand — and spec 002 §2 advances `next_eligible_at` only _after_
  a fetch completes, so the second request left inside the same claim with
  **no politeness gap at all**. On a 3,400-page AUTO domain with `render`
  stopped that is 6,800 supplier requests instead of 3,400, at double the
  configured per-host rate, returning a page extraction had already rejected
  as empty. The seam now takes the static page it is given.
  **(b) a sidecar 500 was charged to the supplier.** `render/src/index.js`
  answers 500 when the browser will not launch or a context cannot be
  created — a `/dev/shm`-starved Chromium that cannot relaunch after a
  recycle answers 500 to _every_ request. That is "the sidecar is
  unavailable", which spec 012 §4 answers with "pending, stalled, not
  failed". Worse, `AutoFetcher` falls back on `Backpressure` only, so AUTO
  domains would not have fallen back at all for the one status the sidecar
  emits when its browser is broken. The slice's own argument — our service
  being down must not be charged to a supplier — had been applied to
  connection-refused and not to that.
  Also acted on: the worst-case wall time of one `fetch()` was
  `2 × (timeout_ms/1000 + 10 s)`, which at `timeout_ms = 60000` is **140 s**
  and outlives ADR-0026's 120-second lease — the sweep would return the row
  while the fetch was still running and another worker would take the same
  URL. Now clamped to the sidecar's own 30 s ceiling, with the arithmetic
  asserted against the lease. And the `# type: ignore[arg-type]` whose
  comment said "kwargs are checked by the dataclass" is gone: a plain
  dataclass checks nothing at runtime, so after the ignore nothing checked
  them at all.
- **integrator** — `make check` green.

## Open questions

1. **`FetchedPage`'s docstring is wrong about `fetch_path`.** It says
   `fetch_path` makes an AUTO fallback "observable in the data rather than
   inferred from a log", but AUTO fetches static first by design, so
   `fetch_path = STATIC` is both the healthy and the degraded outcome. That
   is why this slice adds `fell_back_from`. The docstring is corrected here;
   whether the **field** is the right answer, versus a third `FetchPath`
   value or a column of its own, is a structural call. **For the human** — if
   the answer is a `FetchPath` value, it needs an ADR because it changes what
   that enum means.
2. **`Strategy` now answers two questions.** `structured | selector | llm`
   say which extraction rung produced the fields; `static_fallback` says how
   the fetch was degraded. An observation extracted by the selector rung
   after a static fallback can record only one of the two. Spec 012 §4 and
   TESTING.md §2 both name `strategy = static_fallback`, so this slice
   implements it as specified — but the conflation is real and a second
   column (or a `degraded` boolean) would be the cleaner shape. **For the
   human**, and it wants an ADR either way.
3. **`fetch_rendered_or_fall_back` is not on the `Fetcher` port**, so `1.13`
   must know it holds an `AutoFetcher` — the `render_mode` branch
   `AutoFetcher`'s own docstring claims ADR-0008 removes. Raised by review
   and real. The honest shape is probably for `1.13` to own the AUTO
   decision outright rather than for this composition to offer half of it;
   deciding that now would be designing `1.13` from here. **For the human.**
4. **An AUTO second chance is issued from the static pool**, so it is outside
   spec 002 §6's "3 in flight" rendered budget. AUTO domains can therefore
   oversubscribe the sidecar's three contexts and manufacture the very 503s
   this code treats as backpressure. `1.13` owns pool sizing. **For the
   human.**
5. **The sidecar's `truncated: true` flag is dropped.** `render/src/index.js`
   sets it per spec 012 §3, and the adapter reads `html` and discards it — so
   a 10 MB-capped page is extracted as if complete and `1.11` would write a
   `content_hash` over half a document with nothing recording why.
   `FetchedPage` has no field for it; naming it here rather than silently
   losing it.
6. **`wait_until` is hard-coded to `networkidle`** and `FetchRequest` has no
   field for it, so a domain can never ask for `load`. `networkidle` is the
   most timeout-prone of the three: a supplier with long-polling or chatty
   analytics burns the full budget on every page, 504s, retries once and
   fails. The spec lists three values and the adapter implements one.
7. **AUTO's extraction-driven retry is not implemented** and cannot be: the
   `empty_extraction` predicate arrives in `1.10` and the orchestration in
   `1.13`. `AutoFetcher` carries a named hook and no approximation.
