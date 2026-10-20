# Testing strategy

The point of the test suite is to catch the two failures that actually hurt:
**getting blocked** and **silently extracting wrong data**. Coverage
percentage is not a goal; those two are.

---

## 1. Layers

| Layer       | Tool                        | Runs against                     | Speed    |
| ----------- | --------------------------- | -------------------------------- | -------- |
| Unit        | pytest / vitest / node:test | Nothing external                 | ms       |
| Integration | pytest, BFF suite           | **Real Postgres**                | seconds  |
| Contract    | pytest + openapi            | Both running APIs                | seconds  |
| End-to-end  | Playwright                  | The whole stack through the edge | a minute |

End-to-end tests go through **the edge on :8080**, not directly to a service.
Testing against `api:8000` skips the routing that is the most likely thing to
be misconfigured.

### Never SQLite

Integration tests run against real Postgres, in the compose stack, on a
separate `spydra_test` database. `SKIP LOCKED`, `DISTINCT ON`, partial unique
indexes, arrays and JSONB operators either do not exist in SQLite or behave
differently. A SQLite suite would be testing a different system — and the
concurrency guarantee is the thing most worth testing.

Each test gets a transaction that is rolled back, except the concurrency tests,
which need real committed rows and clean up after themselves.

### No network, ever

Unit and integration tests make no outbound requests.

- HTTP: **`httpx2.MockTransport`** — a handler function returning
  `httpx2.Response`, passed as the client's transport. No mocking library
  (ADR-0028: respx supports neither httpx2 nor Python 3.15, and
  `MockTransport` ships in the client so it cannot fall behind it). The rule
  this serves is unchanged: no network in a unit test.
- Pages: **hand-written** HTML fixtures in `tests/fixtures/pages/`,
  committed, served over loopback by the fixture server (BUILD_PLAN `1.4`).
  Written rather than captured: a fixture must hold still for years, and a
  copy of a real page goes stale, carries someone else's content, and tempts
  a test into re-fetching the original. Each one exists to exercise one
  shape — see §4.
- LLM: a fake `LLMClient` returning canned proposals. The entire proposal and
  verification path is tested without a model running.
- **Rendering: a fake render service.** The Python suite never starts
  Chromium — `RenderServiceFetcher` is tested against a stub returning
  recorded HTML, plus the 503-backpressure and timeout paths. The sidecar has
  its own suite that does drive a real browser.
- Playwright tests serve fixtures from a local static server in the test
  network, not from the internet.

---

## 2. What must be tested

These are not negotiable; each maps to a stated failure mode.

**Politeness (spec 002)** — the guarantee the system exists to keep.

- Two workers, one active domain → never concurrent. Assert on observed fetch
  timestamps, not on mocks.
- Two workers, four domains → four concurrent.
- Killed worker → leased row returns to `pending`, `in_flight` reconciled.
- Three 403s → domain paused, queue abandoned.
- `Crawl-delay: 10` raises a 2 s delay; `Crawl-delay: 1` does not lower it.
- robots.txt 5xx → domain skipped for the run.
- Inter-request gaps show jitter, not a constant.

**Silent extraction failure (spec 003)** — the one that produces no error.

- A failing field is **recorded** in `page_observations.validation`, writes
  the observation, and does **not** route to `unknown_pages` or halt the
  domain (ADR-0027 — nothing is `required`, so a validation failure is
  evidence, never control flow).
- A template declaring `required: true` is **rejected** by the loader, not
  ignored.
- 21% of a domain's pages yielding `empty_extraction` breaks the domain and
  halts it; 19% does not. **Counted on empty extraction, not on per-field
  validation** — counted the latter way this never fires and a redesign
  fills the dataset silently, which is the failure this list exists for.
- **Only pages with a prior non-empty observation count** (ADR-0030). A
  domain whose links are half dead keeps crawling; the same domain after a
  redesign halts. Both assertions, or the soft-404 fixture proves nothing.
- A first run with 21% empty moves the domain to `awaiting_approval`, not
  `broken`.
- A price of "POA" is a validation failure, not `0.00`.
- Unchanged page → identical `content_hash`, no duplicate full row.
- A redesigned fixture (same URL, new markup) produces `empty_extraction`.

**LLM verification (spec 007)**

- A proposal whose claimed text does not match the DOM is discarded.
- A zero-match selector never reaches the API response.
- `nth-of-type` capped at `medium` confidence.

**Migrations**

- `upgrade head` from empty, then `downgrade base`, on every migration. CI
  fails an irreversible migration.

**Contract (ADR-0013)**

- `make types` on a clean tree produces no diff, for **both** schemas.
- Every documented endpoint in specs 005 and 011 exists with the documented
  method.

**Service boundaries (spec 010)**

- The BFF role cannot `INSERT` into `crawl.runs`. This is a test, not a
  comment — it is the only thing standing between two schemas and a
  distributed monolith.
- The API role cannot see the `ui` schema.
- SSE through the edge arrives incrementally: emit one event per second and
  assert on **arrival times**, not just on the final payload. A buffered
  stream passes a naive test and fails the user.
- Stopping `bff` leaves a running crawl unaffected.
- Stopping `render` leaves static domains crawling and `auto` domains falling
  back with `strategy = static_fallback`.

**Scheduling (spec 011)**

- A due schedule fires exactly once with two loop iterations overlapping.
- A BFF restarted after downtime fires a missed window once, not N times.
- A schedule whose domains are mid-run is skipped and recorded.

---

## 3. Frontend

- **Vitest + Testing Library** for reducers, hooks and components with logic.
  Do not snapshot-test markup; snapshots of a design system are churn.
- `useRunEvents` is tested against a fake `EventSource`, including the
  reconnect-and-backfill path.
- **Playwright** for the one journey that matters end to end:
  seed → propose → review → approve → run → inspect a product.
- Both themes are asserted on the screens where colour carries meaning
  (Domains, Run monitor, Template review).
- Accessibility: `axe` assertions on each screen; keyboard traversal of the
  review screen.

## 4. Fixtures

Hand-written, one file per **shape**, with invented host names. The names are
fictional on purpose: nothing here is a copy of a real page, and a reader
should not go looking for the original.

```
tests/fixtures/
  pages/
    vantage-abrasives/product.html        well-formed, selector path
    orbis-components/product-jsonld.html  schema.org/Product, structured path
    orbis-components/product-stripped.html same page, JSON-LD removed
    northfield/product-redesigned.html    same URL, selectors no longer match
    mertens/product-rendered.html         content only after JavaScript
    mertens/product-missing.html          soft 404: HTTP 200, no product
  robots/{permissive,crawl-delay,disallow-all}.txt
  llm/{good,malformed,hallucinated}.json
  render/{rendered-ok.json,timeout.json,503.json}
```

**The redesigned fixture is the most valuable one in the suite.** It is the
only way to test the failure that produces no error — and with nothing
required (ADR-0027), it is `empty_extraction` that must fire on it.

**The soft 404 is the one most easily forgotten.** A catalogue with dead
links returns 200 and no product, which is indistinguishable from a redesign
unless something tells them apart — and at 20% it would move a healthy domain
to `broken`. Spec 003 §3 has no answer for it yet; the fixture exists so the
question cannot be skipped silently.

## 5. CI

CI runs `make check` — the same command, the same images, no separate
pipeline definition that can drift. A PR that cannot pass it locally cannot
pass it in CI, which is the point.

Flaky tests are quarantined and fixed, not retried. A retry on a concurrency
test hides exactly the bug it exists to find.
