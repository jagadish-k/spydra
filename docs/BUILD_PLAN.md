# Build plan

Seven phases. **Each ends with something that runs end to end** — not a layer,
not a set of classes, but a thing you can execute and watch work.

The order follows **risk, not interest**. Phases 0–2 contain everything that
is hard to change later: queue semantics, the politeness model, URL
canonicalisation, the observation schema. Phases 4–6 are additive and slot
into ports that already exist.

> The common failure mode for a project like this is to build the model
> integration first because it is the novel part, then discover the scheduler
> cannot support it. The strategy chain and the `LLMClient` port are designed
> so phase 4 adds a rung and an adapter, nothing more. **Do not reorder.**

## How to use this

- Work one phase at a time, top to bottom. Tasks within a phase may be
  reordered where there is genuinely no dependency — but check, and say so in
  the task file. Phase 1 is strictly linear and says why.
- Tick boxes as you go. The box is ticked when the **definition of done** in
  `AGENTS.md` holds — not when the code is written.
- A phase is complete when its **exit criteria** pass. Demonstrate them; do
  not assert them.
- If a task turns out to need a decision that is not in `docs/adr/`, stop and
  write the ADR first.
- **The gate exists before the work it gates.** The Makefile, the hooks and
  the agent definitions are the first three tasks, not the last three.

---

## Phase 0 — Scaffold

_Nothing works yet. The goal is that `make check` passes on an empty project,
so every later phase has a gate to pass — and that the gate exists before the
work it gates._

**The gate comes first.** Tasks `0.1`–`0.3` build the Makefile, the hooks and
the agent definitions before any service exists. They are plain host commands
with no dependencies, so they work from the first minute, and every commit
from `0.4` onward is already gated. Building them at the end of phase 0, after
a dozen ungated commits, is the common mistake.

- [x] `0.1` Repository skeleton per `AGENTS.md` § Repository layout —
      `backend/`, `bff/`, `render/`, `frontend/`, `docker/`, `scripts/`.
      Plus `.gitignore` and **`.env.example`** (committed; `.env` never is).
- [x] `0.2` `Makefile` with every target in `DEVELOPMENT.md § Commands`.
      Targets whose service does not exist yet **succeed with a skip message
      rather than failing** — `make check` must be green on an empty project
      or it cannot gate the rest of phase 0. Include the granular targets the
      hooks call: `fmt-staged`, `fmt-staged-js`, `typecheck-changed`,
      `typecheck-changed-py`, `agents`, `generated`, `hooks`.
- [x] `0.3` `make hooks` wires `core.hooksPath` to `.githooks/`, and
      `make agents` runs `scripts/gen-agents.py` on the host. **Verify all
      three hooks fire**: a long commit subject is rejected, a staged `.env`
      is rejected, a push to `develop` is refused. Time pre-commit and
      confirm it is under the 10 s budget (`WORKFLOW.md` §2).
- [x] `0.4` Dockerfiles: `api`, `worker` (**no browser**), `render`
      (Playwright Node image), `bff`, `web`.
- [x] `0.5` `compose.yaml` per `DEVELOPMENT.md` — seven services, the
      `egress` network for `render`, `shm_size: 1gb`, named volumes for both
      `node_modules` and the venv, `extra_hosts` for the host LLM.
- [x] `0.6` `docker/Caddyfile` with the four routes. **Verify SSE is not
      buffered** before moving on — the rule ordering and `flush_interval -1`
      are the two ways to get this wrong (spec 010 §2).
- [x] `0.7` `docker/init-schemas.sql` — `crawl` and `ui` schemas, two roles,
      grants. Assert the BFF role cannot write `crawl` (spec 010 §3).
- [x] `0.8` Backend: FastAPI with `GET /api/crawler/healthz`, ruff + mypy
      strict + import-linter. The contract forbids `domain/` importing
      `adapters/`.
- [x] `0.9` BFF: Fastify with `GET /api/ui/healthz`, TypeBox, ESLint,
      OpenAPI document published.
- [x] `0.10` Drizzle wiring (ADR-0021): `bff/drizzle.config.ts` with
      `schemaFilter: ['ui']`, `make revision-ui`, `make drizzle-pull`, one
      trivial `ui` table proving generate → migrate → migrate-down, and the
      test asserting every file in `bff/drizzle/` mentions only `ui.`.
- [x] `0.11` Render sidecar: `POST /render` + `GET /healthz`, context pool,
      resource blocking (spec 012).
- [x] `0.12` Frontend: Vite + React 19 + TS strict; `styles/theme.css`
      importing `tokens.css` and `tailwind-theme.css`; ESLint flat + Prettier.
      **Assert `bg-red-500` fails the build** (ADR-0018).
- [x] `0.13` Alembic initialised for `crawl`; empty baselines run both ways
      under `make migrate` / `make migrate-down` alongside the Drizzle chain.
- [x] `0.14` `make generated` produces `schema.crawler.d.ts`,
      `schema.ui.d.ts`, `bff/src/db/schema/crawl.generated.ts` and the four
      sets of agent adapters, and `make check` fails when any is stale.
      **Prove it twice**: change a `crawl` column and watch the BFF build
      break; edit a role in `docs/agents/` without regenerating.
- [x] `0.15` pytest + vitest + the BFF suite wired, one trivial test each.
      `make check` now actually runs them instead of skipping.
- [x] `0.16` CI running `make check` on a clean checkout, plus
      `make migrate-down`.
- [x] `0.17` Agent team smoke test: one trivial slice
      (`chore/0.17-hello-slice`) end to end — planner writes
      `.tasks/<branch>.md`, an implementer changes one file, the test role
      adds one test, the reviewer reads the diff, the integrator runs
      `make check` and opens the PR. **The point is to find out whether the
      handoff works while the stakes are a hello-world**, not to produce the
      change.

**Exit:** `make up` gives a working stack reachable at
`http://localhost:8080`; `make check` is green; the frontend renders a page
using a design token and the theme toggle works; an SSE test endpoint
streams through the edge **unbuffered**; the BFF cannot write `crawl`; the
three git hooks fire and pre-commit is under 10 s; and one slice has been
through the full agent handoff.

> `0.6` and `0.7` are the two that will cost you a day each if deferred.
> Buffered SSE looks like a frontend bug, and a missing grant looks like
> nothing at all until the BFF quietly writes a table it should not.

> **Run phase 0 as one branch** (`chore/phase-0-scaffold`), mostly
> sequentially. There is nothing to parallelise yet. The agent team starts
> paying for itself at phase 1 (`docs/WORKFLOW.md` §5).

---

## Phase 1 — Crawl a site end to end, both fetch paths

_No UI, no model. The scheduler and the data model are the two things most
expensive to get wrong, so they come first and are proven in isolation._

**This phase is strictly linear.** Every task depends on the one above it, and
the order is dependency order rather than preference — `1.9`'s politeness gate
fetches `robots.txt`, so it cannot precede the fetcher in `1.6`. An earlier
plan ran `1.5`–`1.11` as three parallel lanes; that is abandoned. ADR-0022
still permits parallel slices across disjoint file sets, but nothing in this
phase has a disjoint file set from the task before it.

**Nothing in this phase crawls the public internet.** Every test and the exit
criterion run against the local fixture site built in `1.4`. `docs/TARGETS.md`
records example sites for the operator to try by hand once the UI exists
(phase 3); they are not inputs to any task here, and no task is blocked on
choosing or reaching one.

- [x] `1.1` Full schema migration per [spec 001 §1](specs/001-domain-model.md).
      One migration, one unit — there is no production data to preserve.
      **Done:** 12 tables, `page_current`, two enums, the partial unique
      indexes, `CHECK (in_flight >= 0)` (ADR-0026); up/down/up proven.
- [x] `1.2` Domain entities and the lifecycle transition function (spec 001
      §2–3). Pure, no I/O. **Done**, with the `Frontier`, `Fetcher` and
      `Clock` ports (ADR-0008) defined here rather than beside their first
      adapter, so no adapter authors its own contract.
- [x] `1.3` Example target sites recorded in `docs/TARGETS.md` with each
      one's `robots.txt` and terms status. **Done, and deliberately not a
      dependency:** these exist for the operator's own manual iteration in
      phase 3. Nothing below reads them.

- [x] `1.4` **The local fixture site.** Hand-written HTML under
      `backend/tests/fixtures/` served over loopback inside the test network,
      plus the tiny static server that serves it. One page per shape the
      extraction chain must handle, and the shapes are the point:
      `schema.org/Product` JSON-LD present; the same page with the JSON-LD
      removed so it falls through to selectors; a redesigned variant at the
      same URL whose selectors no longer match; a page whose content arrives
      only after JavaScript; a soft-404 that returns 200 with no product; and
      `robots.txt` variants (permissive, `Crawl-delay`, disallow-all).
      Everything after this depends on it, and `AGENTS.md` rule 14 is
      unachievable without it.
      **Done when:** `make test-api` and the sidecar suite both reach it with
      no outbound network, and every shape above has a page.
      **Done:** 7 pages, 3 `robots.txt` variants, a stdlib loopback server and
      11 tests over the fixtures themselves — because a fixture that quietly
      stops exercising its shape takes its dependent test down silently and
      the test still passes. `robots.txt` is served **per host**, since
      politeness is a per-host property (spec 002 §5) and one host could not
      exercise `Crawl-delay` and disallow-all in the same run. The JSON-LD
      twins are generated from one source so they cannot drift apart and make
      the rung-ordering test meaningless.

- [x] `1.5` **Render sidecar acceptance suite** — the six criteria in
      [spec 012 §6](specs/012-render-sidecar.md) that a real browser can
      prove against `1.4`'s fixtures: JS-dependent content present after
      render and absent from the raw response; a fourth concurrent request
      queueing then 503ing rather than opening a fourth context;
      `block_resources` measurably reducing render time; `alert()` not
      hanging the request; the browser recycling past its page threshold
      without dropping an in-flight render; an oversized response truncated
      and flagged. The service itself shipped in phase 0 and its helpers are
      unit-tested; its HTTP contract is not, and `1.7` depends on it.
      **Done when:** `make test-render` exercises all six through
      `POST /render`, and the four remaining §6 criteria are listed in the
      task file with the phase that will cover them.
      **Done:** 6 cases through `POST /render` against `1.4`'s fixture site,
      every one mutation-tested — and two of the six were **not** covered on
      the first pass, which is the whole argument for the mutation step: `A1`
      stayed green with the browser's DOM removed from the response (the
      fixture carries its product's class names in a JS string literal), and
      `A4` stayed green with the dialog guard deleted (Playwright
      auto-dismisses when no listener is attached). Both are written up in
      the task file. **`make test-render` could not fail before this task**:
      `render` had no bind mount, so the target ran the image's copy of the
      suite and a planted failing test exited 0. The four remaining §6
      criteria are in the task file with a phase each; one of them — the
      network-isolation criterion — has **no owning task** and is raised
      there rather than resolved.

- [ ] `1.6` **`HttpxFetcher`** behind the `Fetcher` port from `1.2`. An HTTP
      error status is a successful fetch — deciding what a 403 or 429 means
      belongs to `1.9` (ADR-0004). Tested with `httpx2.MockTransport`
      (ADR-0028), no mocking library and no network.
      **Done when:** the status table, timeout, redirect and `FetchFailed`
      paths are covered, and the user-agent from `.env.example` is asserted
      on the outgoing request (ADR-0004).

- [ ] `1.7` **`RenderServiceFetcher`** behind the same port — HTTP to the
      sidecar, 503 as `Backpressure` rather than a fetch failure, 504
      retried once (spec 002 §6, spec 012 §1). Adds `static_fallback` to
      `page_observations.strategy` for `render_mode = auto`, which spec 001
      §1 does not yet list and TESTING.md §2 requires.
      **Done when:** `1.6`'s tests are unchanged — if they need changing the
      port is wrong, not the test — and the sidecar being down leaves
      `static` domains unaffected, stalls `rendered` ones honestly and makes
      `auto` fall back and record it. **Also closes spec 012 §6's "the Python
      image contains no `playwright` package and no browser"** — deferred
      here from `1.5` because it needs no browser, and asserted nowhere
      today: `docker/api.Dockerfile` and `docker/worker.Dockerfile` only say
      so in a comment. This is where spec 012 §1's "no browser dependency at
      all" first carries weight.

- [ ] `1.8` **`PostgresFrontier`**: the claim query exactly as
      [ADR-0026](adr/0026-claim-locks-the-domain-row.md) specifies it, the
      lease-expiry sweep, completion, `release()` and `abandon_domain()`
      (spec 002 §1–3). The sweep is load-bearing, not hygiene: `in_flight`
      gates claiming, so a counter left high by a dead worker stalls its
      domain until the sweep reconciles it.
      **Done when:** two real workers on two real connections against one
      active domain never claim concurrently, and four domains reach four
      concurrent claims — real rows, real elapsed time, no mocked clock
      (TESTING.md §2).

- [ ] `1.9` **Politeness gate**: `robots.txt` once per domain per run with
      `Crawl-delay` as a floor and 5xx failing closed, jitter in [0.7, 1.3],
      the ×2 backoff capped at 15 min, the 10% decay on success, and three
      consecutive 403s pausing the domain and abandoning its queue rows
      (spec 002 §4–5, ADR-0004).
      **Done when:** `TESTING.md` §2's politeness list passes against
      `1.4`'s robots fixtures, inter-request gaps show jitter rather than a
      constant, and no test retries through a 403.

- [ ] `1.10` **Extraction chain** with the `structured` and `selector` rungs,
      the transform table and validation (spec 003 §1–3). Validation records
      and never routes: no field is required (ADR-0027). This is where
      `empty_extraction` is implemented — one predicate in
      `extraction/validation.py` with three callers, which is why it lands
      before the observation writes and the worker.
      **Done when:** spec 003 §5 passes against `1.4`'s fixtures, including
      the JSON-LD page extracting without a template, the same page without
      it falling through to selectors, and "POA" failing currency validation
      rather than becoming `0.00`.
      The soft-404 question this task used to carry is settled by
      [ADR-0030](adr/0030-empty-needs-a-prior.md): the predicate is unchanged
      and the _threshold_ is what excludes a page with no prior observation.
      `1.11` implements that; `1.10` only has to make the predicate a
      function with one definition.

- [ ] `1.11` **Observation writes** with `content_hash` over the **normalised
      extracted fields**, never the raw markup (spec 003 §4, ADR-0007).
      Routes `empty_extraction` to `unknown_pages` and moves a domain to
      `broken` past 20% — ADR-0027's predicate on the final observation after
      any `auto` fallback, counting only pages with a prior non-empty
      observation (ADR-0030). A first run past 20% goes to
      `awaiting_approval` instead, because nothing can have regressed yet.
      **Done when:** re-extracting an unchanged page yields an identical
      hash; the redesigned fixture trips `broken` while the soft-404 fixture
      does not, however many of them there are; and 21% trips it while 19%
      does not.

- [ ] `1.12` **Asset enqueue and backpressure** — the scheduler half only
      (spec 002 §7, ADR-0003): a page worker resolves image URLs, inserts
      `asset_queue` rows and moves on without ever blocking on an image, and
      page claiming slows once the pending queue passes 10,000. **Nothing
      drains the queue until `5.2`**, which is where spec 008 and the
      `AssetGate` live — building the gate here would be building it for no
      consumer.
      **Done when:** a page yielding six images leaves six `asset_queue`
      rows and the page worker's own timing is unchanged, and a queue seeded
      past the threshold measurably slows page claiming (TESTING.md §2).

- [ ] `1.13` **Worker process** — the three `asyncio.TaskGroup` pools over one
      connection pool (ADR-0003), the sweep at the start of every claim-loop
      iteration. Replaces the placeholder `command` in `compose.yaml`. It
      emits no `run_events` yet — that is `2.8`, which adds emission to the
      worker it inherits, and there is no consumer before phase 3.
      **Carries spec 009 §1 for the crawl path**: structured logging at the
      volume that spec sets, which is a property of how the worker logs and
      cannot be added by a later pass. Until this task, "logging" appeared
      nowhere in this plan and the only observability task was `5.11`.
      **Done when:** `make up` runs a worker that crawls `1.4`'s fixture site
      to completion and stops cleanly on SIGTERM mid-run, and a 1,000-page
      run at `info` stays under spec 009 §5's line budget with no HTML body
      or credential in any line.

- [ ] `1.14` A YAML template loader so a domain can be configured without a
      UI. **This is scaffolding with a known end date** — it is deleted in
      `3.2` once templates come from the API. Do not build a format anyone
      could grow attached to: no schema, no validator, no inheritance. It
      **rejects** `required: true` rather than ignoring it (ADR-0027).
      **Done when:** the exit criterion below runs from a YAML file, and a
      template declaring `required: true` is refused with a message naming
      ADR-0027.

**Exit:** the local fixture site crawled politely end to end from a YAML
template — a static page **and** a JavaScript-dependent page, both fetchers
exercised by the same scheduler, data in Postgres, and asset rows enqueued
(drained in `5.2`).
The politeness tests in `TESTING.md §2` pass. Stopping the `render` service
leaves static crawling unaffected and makes `auto` record `static_fallback`.

> Both adapters ship here deliberately. A port with one implementation is an
> untested abstraction, and rendering is a supported capability rather than a
> contingency.

> **Why the exit is a fixture site and not a real supplier.** A phase gate
> that depends on a third party's uptime, markup and tolerance is a gate that
> fails for reasons unrelated to the code — and one of the example sites in
> `1.3` started returning 403 within a day of being recorded. The crawler is
> generic by design; proving it against markup shaped like the real thing
> proves the crawler, and the operator points it at real sites from the UI in
> phase 3, which is also the first point at which they can watch it behave.

---

## Phase 2 — Discovery and the queue

_Turn a seed into a full product set without wandering off-site or exploding
on facets._

**Linear, like phase 1**, and for the same reason: `2.4` dedupes what `2.3`
extracts from what `2.2` canonicalised. Nothing here has a disjoint file set
from the task above it.

- [ ] `2.1` **Grow the fixture site** (`1.4`) with the shapes this phase
      needs: paginated listings, a faceted listing whose filter combinations
      would explode, a mega-menu that links the whole tree from depth 0, a
      subcategory nest, and a crawler trap — a repeating path that generates
      URLs for ever. Every task below is tested against these.
      **Done when:** each shape has a page, and the trap is genuinely
      unbounded so that `2.5`'s caps are the only thing that stops it.

- [ ] `2.2` **URL canonicalisation and `url_hash`** (spec 004 §2): query
      parameters sorted, tracking parameters stripped, meaningful ones kept,
      `rel="canonical"` honoured within the host.
      **Done when:** `?b=2&a=1` and `?a=1&b=2` hash identically, `utm_source`
      is stripped while `?page=2` survives, and a `rel="canonical"` pointing
      elsewhere on the same host collapses two URLs into one page row
      (spec 004 §5).

- [ ] `2.3` **Link extraction from discovery rules** (spec 004 §1) —
      `product_links`, `next_page`, `subcategory_links`, the per-domain
      allow/deny patterns and `max_depth`. Discovery never leaves the
      registrable domain.
      **Done when:** depth-6 links are not enqueued at `max_depth = 5`, an
      off-host link is dropped, and a faceted listing is capped by
      `deny_patterns`.

- [ ] `2.4` **Dedupe within a run and breadth-first enqueue** — `UNIQUE
(run_id, url_hash)` (spec 001 §1) with listings drained before
      products, which is what keeps the frontier full (spec 002 §1).
      **Done when:** the same URL discovered twice in one run enqueues once
      and in a _later_ run enqueues again, because that is a re-crawl.

- [ ] `2.5` **Trap defences** (spec 004 §3): per-run and per-domain URL caps,
      the depth cap, repeating-path detection, scheme and length rejects.
      **Done when:** `2.1`'s unbounded trap terminates, and a run breaching
      the per-domain cap halts that domain and names the cap as the reason
      rather than reporting a clean finish.

- [ ] `2.6` **Mega-menu containment** (spec 004 §3a): a `subcategory_links`
      rule is scoped to its container, and the dry-run reports when a rule
      discovers the whole tree at depth 0. **This is the discovery bug that
      looks like a working rule** — it finds everything, so it reads as
      success until the queue is the entire site.
      **Done when:** a `nav a` rule on `2.1`'s mega-menu fixture is caught by
      the dry-run, and a fixture whose subcategory links are `display:none`
      is still discovered (spec 004 §5).

- [ ] `2.7` **Run lifecycle** — create, pause, stop, complete, and
      `runs.stats` rolled up at completion (spec 001 §1). Abandoned rows are
      reported, never deleted (ADR-0004).
      **Done when:** a stopped run reports the work it did not do, and
      `stop_reason` is set for every non-`completed` terminal state.

- [ ] `2.8` **`run_events` writer** — monotonic `seq` per run, the bounded
      log that lets a reconnecting SSE client be backfilled rather than shown
      a gap (spec 001 §1, ADR-0012). Built here because the worker emits
      them; `1.13`'s worker deliberately emits none.
      **Done when:** `UNIQUE (run_id, seq)` holds under two workers emitting
      concurrently, and the log is bounded rather than growing with the run.

- [ ] `2.9` **CSV seed parsing** with per-row validation and no HTTP
      (spec 004 §4). Rejects report the row and the reason.
      **Done when:** a file with one bad row imports the rest and names the
      failure, and nothing in the parser can make a network call.

- [ ] `2.10` **Dry-run discovery as a library function** (spec 004 §4) —
      what _would_ be enqueued, grouped by matching rule, with no writes.
      The seeds screen (`3.13`) and the review screen (`3.14`) both call it,
      which is why it is a function and not an endpoint.
      **Done when:** it reports counts per rule against `2.1`'s fixtures and
      provably writes nothing — asserted, not assumed.

**Exit:** a category seed yields the full product set for the fixture site's
catalogue without leaving the host and without a facet explosion; the dry-run
reports what would be enqueued, grouped by matching rule. The fixture site
grows the pagination, facet and subcategory shapes this phase needs — the
same reason phase 1 does not crawl a real supplier.

---

## Phase 3 — API, UI and review

_The operator can onboard a domain without touching the filesystem.
Selectors are still hand-written; the model comes next._

**3a — the draft model, before anything renders it**

- [ ] `3.1` `crawl.template_drafts` and `crawl.field_vocabulary` migrations
      (spec 013 §1–3); vocabulary seed + the test asserting `column_name`
      names a real column. **This lands before the review screen on
      purpose** — the screen is the most expensive thing in phase 3 and
      building it against the final state shape costs nothing now and saves
      rewriting it in phase 4.
- [ ] `3.2` `TemplateDraft` + `FieldCandidate` domain objects, provenance and
      verification sub-objects included from the start (spec 013 §2). Delete
      the YAML loader from `1.14`.
- [ ] `3.3` The shared verify → merge-per-field → rank pipeline (spec 013
      §4). **One implementation, used by every authoring mode.** If a second
      appears, ADR-0019 has been broken.

**3b — the surfaces**

> **Every UI task below carries state coverage in its definition of done.**
> The states are `UI_STATES.md` §1 (loading · empty · error · populated, plus
> partial where a surface aggregates) and §4 (what that screen also has). A
> component or screen PR that ships only the populated path is incomplete,
> not a PR with a follow-up, and `spydra-reviewer` reads the matrix to say
> which state is missing (ADR-0025).
>
> **Which screen is which, and what it looks like:** `docs/SCREENS.md` is the
> registry — it gives each screen its Figma node id, mockup, spec and frame
> count, and it is the only place screens are enumerated. The **Figma frame**
> is authoritative for layout in every state; `design/mockups/` is a runnable
> cross-check, not an authority (ADR-0031). Enumerate the Figma file with
> `figma.root.children` through `use_figma` — a bare `get_metadata` reports
> only the pages loaded in the operator's editor.
>
> **Build from the component, not from the screen frame** (ADR-0032 — anything
> above a primitive is a component). **Every screen frame is now a composition
> of instances**: 49 components, 1,761 instances across 62 frames, with four
> one-of-a-kind containers deliberately left as frames and listed in
> `docs/COMPONENTS.md` §3. So the frames are now a reliable guide to which
> component a region is — read `COMPONENTS.md` §1 for what each is used by,
> and §4 before changing any component, because three Figma constraints there
> each cost a visual regression to find.

- [ ] `3.4` Crawler API: domains, seeds, templates, drafts, runs, pages
      (spec 005 §2, spec 013 §5).
- [ ] `3.5` BFF: schedules with the fire loop, saved views, preferences, and
      `GET /api/ui/overview` (spec 011). The scheduling loop's once-only
      firing is the part to test properly.
- [ ] `3.6` SSE endpoint with `Last-Event-ID` backfill from `run_events`
      (spec 005 §3). **Backfill is part of this task, not a follow-up.**
- [ ] `3.7` `make types` wired for **both** schemas; generated client
      (ADR-0013, ADR-0015).
- [ ] `3.8` Frontend shell: `AppShell`, routing, theme with no-flash load.
- [ ] `3.9` Design-system components (spec 006 §2) — build the whole set
      before the screens, so screens compose rather than improvise.
      **Each ships its full variant set from `UI_STATES.md` §3**, not only its
      populated path. **Scope: the shared sets only** — all seventeen §3a
      variant completions plus the twenty §3b sets used by three or more
      screens. The other fourteen land in the task for their screen, still
      before it renders. ADR-0025 §scope carries both lists; read it rather
      than re-deriving them. `Skeleton` heights are **asserted against
      `--sp-row-comfortable` in a test** — a skeleton of the wrong height is a
      layout jump no screenshot review catches.
      **Read `docs/COMPONENTS.md` §5 first.** It is the measured state of the
      Figma library against the matrix: 49 components exist, four of the
      seventeen §3a completions are already done, five components exist under
      a different name than §3 gives them, and seventeen §3b sets are still
      unbuilt. Two to land early: `Metric tile State=unavailable` — the five
      Partial frames already override a `Value` to an em dash, so the
      component and the frames disagree until it exists — and a size-tolerant
      `Skeleton`, whose `Shape=Card` overflows when resized, which collides
      with §1's requirement that a skeleton hold the height it replaces.
      Text properties are **not** required to carry content — an instance
      overrides its own text — so add them only where a developer will read
      the component's API, and capture a baseline first because adding one can
      reset existing overrides (it reset 5 of 300).
- [ ] `3.10` Domains screen, sorted by health ascending, fed by the BFF's
      `/overview` in **one** request. Includes first-run empty, filtered
      empty — different sentences, different actions — and **partial
      counters**, which is why every counter in spec 011 §5 is nullable
      (`UI_STATES.md` §4, ADR-0025).
- [ ] `3.11` Schedules screen — list, create, edit, fire history (spec 011
      §1, §3, §4). **Unblocked 2026-10-20.** `SCREENS.md` §11 specifies it,
      registry row 11 maps it to Figma `81:6826`, and `UI_STATES.md` §4 lists
      its states. Six frames: populated, loading, both empty sub-cases, error
      and partial. It is also ADR-0032's worked example — **it contains no
      hand-drawn component**, so build it by composing `Schedule row`,
      `Fire row`, `Schedule state`, `Metric tile`, `Table header cell`,
      `Select`, `Pagination` and the shell, and treat any urge to hand-roll a
      row as the signal that a component is missing a text property.
      **Done when:** a skip is visible as an outcome, not as an absence — a
      schedule skipped because its previous run was still active reads as
      skipped with its reason (spec 011 §3), because showing that as "nothing
      happened" is what makes an operator start the run by hand.
- [ ] `3.12` Domain detail with template versions and diff.
- [ ] `3.13` Seeds screen with the mandatory preview step.
- [ ] `3.14` **Template review screen** — three panes, live re-resolve,
      sample matrix, discovery rules with dry-run. Reads and writes a
      `TemplateDraft`, so phase 4 adds modes to it rather than rebuilding it.
      **Phase 3 ships the Preview mode only**: the segmented control renders
      Select and Skeleton as disabled segments, and they become live in `4.10`
      and `6.10`. `UI_STATES.md` §4 lists all three because that is the end
      state, not phase 3's.
- [ ] `3.15` **Batch review** — the same review state rendered as a grid.
      Ships now, not later (ADR-0005, `SCREENS.md` §4).
- [ ] `3.16` Run monitor, SSE-driven, with the two throughput series.
      **Acceptance here, not phase 5 hardening:** a test drops the connection
      and asserts backfill from `Last-Event-ID` with no gap in the series.
      Server-side backfill is `3.6`; this is the client half, and the
      reconnecting state must read as backfilling rather than frozen
      (`UI_STATES.md` §4 screen 6).
- [ ] `3.17` Runs history with run comparison.
- [ ] `3.18` Products browser with observation history and field diff.
- [ ] `3.19` Playwright e2e: seed → template → approve → run → inspect.

**Exit:** a domain goes from seed URL to crawled product data entirely
through the UI, and a schedule fires a run unattended. Closing the laptop
mid-run and reopening shows no gap. Stopping the BFF does not affect a
running crawl. No YAML templates remain.

> **Re-read [ADR-0015](adr/0015-service-topology.md) at the end of this
> phase.** If the BFF turned out to be mostly pass-through, collapse it and
> move scheduling into Python. Answer that honestly rather than keeping a
> tier because it is already there. ADR-0021 goes with it if it does.

> `3.9` before `3.10`–`3.18` is the point. Screens built before their
> components produce ten one-off layouts that drift.

---

## Phase 4 — LLM proposals and chat authoring

_The model enters. The scheduler, the chain, the draft pipeline and the
review screen all exist by now, so this adds a rung, an adapter and two new
ways to fill a draft that already works._

- [ ] `4.1` `LLMClient` port + `LlamaServerClient`, with the fake used by
      tests.
- [ ] `4.2` DOM skeletonisation (spec 007 §2), with the node budget and
      stable node indices.
- [ ] `4.3` Proposal request with JSON-schema-constrained output.
- [ ] `4.4` **Deterministic verification** (spec 007 §4). Non-negotiable.
      Feeds the phase-3 rank pipeline rather than a second one.
- [ ] `4.5` **Best-of-N: N=5 at temp 0.7, the ADR-0020 scorer, per-field
      merging.** Do not build the single-greedy-sample version first; the
      scorer is what makes the proposals usable.
- [ ] `4.6` Derived confidence, including the `nth-of-type` cap; escalation
      to the dense model for fields scoring below 60.
- [ ] `4.7` `POST /drafts/{id}/propose`; `awaiting_approval` transition.
- [ ] `4.8` Unknown-pages inbox, grouped by `(domain, reason, url_pattern)`.
- [ ] `4.9` Dismiss-as-not-a-product-page adds a deny pattern.
- [ ] `4.10` DOM-skeleton mode in the review screen's left pane.
- [ ] `4.11` Chat endpoint over SSE, with the hard limits enforced
      server-side — five sample pages, one domain, cannot start a run,
      cannot write `templates` (spec 013 §6).
- [ ] `4.12` Authoring chat screen (SCREENS §10) with provenance badges and
      the visible sample-page counter.
- [ ] `4.13` Draft purge sweep for `discarded` rows older than 30 days.
- [ ] `4.14` Degradation: `llama-server` down blocks authoring only.
      Crawling, scheduling and the UI are unaffected.

**Exit:** a new domain reaches an approved template without a selector being
written by hand, by chat or by `propose`. The chat refuses a sixth sample
page and says why. With `llama-server` stopped, crawling is unaffected.

> Nothing here rebuilds a screen. If a task in this phase finds itself
> rewriting the review screen's state management, phase 3 put the draft
> model in the wrong place and that is worth saying out loud rather than
> working around.

---

## Phase 5 — Assets, reports and hardening

_Everything that is additive and benefits from real data to tune against._

- [ ] `5.1` `make seed-dev` — seed the **database** with two domains' worth
      of crawled rows so a fresh clone has something to look at without
      running a crawl. Distinct from `1.4`, which serves HTML to the crawler;
      this writes observations straight to Postgres. The first-run
      instructions in `DEVELOPMENT.md` already promise it.
- [ ] `5.2` Asset pool, the per-host `AssetGate` and the `AssetStore` port +
      `LocalAssetStore` (spec 008, spec 002 §6, ADR-0008). The enqueue half
      and the backpressure landed in `1.12`; this is the half that drains.
      **`AssetStore` is the fourth port in ADR-0008 and had no task until
      now** — it is named here so storage location stays config rather than
      code.
- [ ] `5.3` Hash-before-decode, resize, WebP, sharded content-addressed paths.
- [ ] `5.4` Asset safety limits — size, type sniffing, decompression bombs.
- [ ] `5.5` Re-tune the asset backpressure against real volume — the
      mechanism shipped in `1.12`; this is the threshold, measured rather
      than guessed, once something actually drains the queue.
- [ ] `5.6` Surface the broken-template detector: the halt itself ships in
      `1.11` (it is the only thing standing between a redesign and silent
      data corruption, so phase 1 cannot ship without it). Here it gets the
      report, the per-field diff against the last working observation, and
      the review path back to `awaiting_approval`.
- [ ] `5.7` Reports: extraction health, broken templates, price changes,
      new/missing, politeness, coverage. CSV + JSON export.
- [ ] `5.8` Reports screen.
- [ ] `5.9` HTML purge sweep on the 7-day TTL behind `make purge-html`;
      pre-run disk check.
- [ ] `5.10` Render-path hardening — sidecar replica count, recycle
      thresholds and per-domain `render_mode` overrides, tuned against real
      volume. The `auto` fallback and `strategy = static_fallback` ship in
      `1.7`; this is sizing, not behaviour.
- [ ] `5.11` Observability sweep against spec 009 — the metrics of §2, the
      surfaces of §3, and whatever phases 2–4 added without logging. **Not
      the first pass**: `1.13` carries §1 for the crawl path, because a line
      budget is designed in, not retrofitted.

**Exit:** a full run over several domains produces images, reports and a
coverage number. The crawl-politeness report is defensible evidence.

---

## Phase 6 — Visual playground

_Last because it is the most build for the least risk, and because it needs
the draft pipeline and the sidecar to already be solid. It is also the phase
most likely to change shape once phases 4–5 have shown where the review time
actually goes — so do not start it early._

- [ ] `6.1` `POST /inspect` on the sidecar (spec 014 §2) — full-page
      screenshot, element geometry, skeleton, **sharing the existing context
      cap and the egress-only network**.
- [ ] `6.2` Full-page scroll before capture, so lazy-loaded content has
      boxes.
- [ ] `6.3` Attribute and class filtering (spec 014 §3) — hashed, utility and
      state classes rejected before generalisation.
- [ ] `6.4` Inspect cache, 30 min, keyed `(url, viewport, full_page)`. **Cache
      hits claim no politeness lock; misses do.**
- [ ] `6.5` Layer 1 generalisation — heuristic ancestor walk, top three
      candidates emitted, not one.
- [ ] `6.6` Layer 2 generalisation — multi-example index elimination. This is
      the layer that earns the phase; budget accordingly.
- [ ] `6.7` Layer 3 — LLM refinement, only below score 60, selectors only.
- [ ] `6.8` Repeating-container detection with all three confirmations
      (siblings, structural similarity, geometry).
- [ ] `6.9` `POST /drafts/{id}/select`; examples persisted in provenance.
- [ ] `6.10` Select and Skeleton modes on the review screen's left pane,
      ancestor walk on `[` / `]`, all matches highlighted.
- [ ] `6.11` `reveal` steps (spec 014 §2a) with every bound enforced, plus
      `network[]` capture. The bounds are the feature; an unbounded version
      is a different program.
- [ ] `6.12` Promote a network-log endpoint to a discovery rule
      (spec 004 §3a, case C), and a `json_source` discovery rule for menus
      whose data ships as inline JSON.
- [ ] `6.13` Re-generalisation from stored examples, for a template broken by
      a redesign. This is the payoff for storing provenance.

**Exit:** a listing and a product template are authored for a previously
unseen domain entirely by clicking, container included, and the result is
indistinguishable in shape from a hand-written template. A selector built
from clicks on two sample pages survives a positional change on a third.

---

## Deferred

Not in the plan; revisit only with a reason.

| Item                                            | Why deferred                                                                                                |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Full-text search over descriptions              | Postgres `tsvector` when there is a query to serve                                                          |
| Export pipeline                                 | Build the exporter when the target format is known                                                          |
| Template inheritance resolution                 | Column exists, logic does not (ADR-0006)                                                                    |
| Tiered coverage / best-effort mode              | Until the coverage report shows the backlog growing faster than it clears                                   |
| Proxy rotation                                  | If it is needed, the polite-crawling assumptions have already failed                                        |
| Free-threaded Python (`cp315t`)                 | Dependencies ship it; nothing needs it yet (ADR-0017)                                                       |
| Replacing the render sidecar with browserless   | The HTTP contract makes it a swap, not a rewrite                                                            |
| Scripted interaction recorder in the playground | Large build, large failure surface; bounded `reveal` and Skeleton mode cover nearly all of it (spec 014 §7) |

---

## Known risks

| Risk                                                                                                                                   | Signal                                                             | Response                                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **Review throughput, not technology, is the constraint.** At one template per domain and ~6 domains/month, 1,200 domains is ~16 years. | Coverage report backlog trend                                      | Batch review ships in phase 3 for this reason. If the backlog still grows, tiered coverage becomes real work.                   |
| JS rendering more common than expected                                                                                                 | Share of domains needing `rendered` after phase 1                  | Rendered pool caps at 3 contexts against 12 static workers, so page throughput drops ~4×. Sizing problem, not a design problem. |
| Supplier data shape varies wildly                                                                                                      | `attributes`/`supplier` JSONB diverging across domains             | JSONB absorbs it; a normalisation pass is unscoped work if cross-supplier querying is needed.                                   |
| Postgres queue contention                                                                                                              | `crawl_queue` index bloat, slow claims                             | Not expected at this scale. The `Frontier` port is the escape hatch (ADR-0002).                                                 |
| **The BFF turns out to be a thin proxy**                                                                                               | After phase 3, count its routes that do real work vs forward       | Collapse it; move scheduling into Python (ADR-0015). ADR-0021 goes with it                                                      |
| The review screen gets rebuilt in phase 4                                                                                              | Any phase-4 task touching its state management                     | The draft model lands in phase 3 (`3.1`–`3.3`) precisely to prevent this. If it happens anyway, say so rather than absorbing it |
| Bleeding-edge stack has thin community knowledge                                                                                       | Time lost to first-encounter problems on Python 3.15 / Tailwind v4 | Budget for it. The docker-native constraint makes a revert one tag away (ADR-0017).                                             |
| Legal posture                                                                                                                          | —                                                                  | Check the ToS of the first targets. A real input to which domains get onboarded.                                                |
