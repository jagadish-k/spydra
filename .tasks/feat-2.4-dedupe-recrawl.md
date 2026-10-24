# feat/2.4-dedupe-recrawl

**Task:** BUILD_PLAN 2.4 · **Spec:** 001 §1 (`crawl_queue` — `UNIQUE (run_id,
url_hash)`; `runs`); 002 §1 (the claim's breadth-first order); 004 §1 rule 6 ·
**ADRs:** 0002, 0006

Stacked on `develop` — **the bottom of the phase-2 stack**. `2.5`–`2.10` (six
more branches) stack on this branch, not on `develop`.

## Contract

**A prove-and-pin slice: the queue's within-run dedupe and its re-fill on the
next run, proven through the real worker.** Expected production delta:
**none**. The mechanism has existed since 1.1 (the constraint) and 2.3 (the
guarded `ON CONFLICT` enqueue); what does not exist anywhere is a _crawl_ that
exercises it. The deliverable is acceptance tests that fail without the
behaviour, chosen mutations proven red, and the BUILD_PLAN tick. If the tests
find a genuine defect, scope its fix into this slice and record it in the
handoff log — do not weaken the test.

### 1. Within-run dedupe, through the worker — the mega crawl

The 2.3 exit crawl never exercises the constraint: every one of its 44 queue
URLs is discovered exactly once (arithmetic in Decided). Halden's mega-menu is
the fixture's built-in shape that changes that: `nav.mega a` links **every
category node on every listing page** (pinned by
`tests/test_catalogue.py::test_the_mega_menu_is_on_every_listing_page_too`).

- Substrate: `FixtureSite`, `seed_halden` from
  `tests/scheduler/test_link_discovery.py` — extend it (a `discovery=`
  keyword defaulting to `EXIT_DISCOVERY`, or an UPDATE of the listing
  template's JSONB after seeding); do **not** fork the helper,
  `tests/adapters/postgres/test_enqueue_guard.py` imports it. Domain static,
  `crawl_delay_ms = 20`, `max_depth = 5`.
- Listing-template discovery: `EXIT_DISCOVERY` with `subcategory_links`
  widened to `"nav.mega a, section.subcategories a, form.facets a"`. Everything
  else unchanged — same deny (facets stay out only through it), same
  `product_links`, same `next_page`.
- Crawl from `EXIT_SEED` with the real worker (`worker()`, `WORKER_STATIC=1`,
  one connection, `wait_until` timeout 120).
- Assert:
  - the run reaches `completed` and **every** queue row is `done` — none
    `failed`, none left `pending`;
  - every category in `catalogue.NODES` is in the queue **exactly once**
    (group by canonical path+query via `path_of`); the seed is one of them;
  - the full `catalogue.PRODUCTS` set (64 SKUs) is observed as product pages
    in this run, each page once (`DISTINCT` over `pages` joined where
    `page_kind = 'product'`);
  - blades' 8 context spellings (`/shop/cutting/blades/p/HT-SB-00X`,
    `context_links=True`) and the seed page's featured `/shop/p/HT-SB-001` are
    **two queue rows and one page row** — that pair is 2.2's page-level
    collapse (rel=canonical), not a dedupe failure;
  - no facet URL and nothing off-host in the queue or the request log, and
    `/shop/deep/6` is never queued: the deny and the depth cap survive the
    wider rule.

### 2. Re-crawl — a later run enqueues again, through the real run-creation path

- Both runs are created by `PostgresConfiguration.apply` — the only production
  run-creation path (the 1.14 loader). Drive it with
  `spydra.load.load(configuration, yaml)` (`parse` → `apply`, exactly what
  `make load` does). YAML: host = the fixture site's `127.0.0.1:<port>`,
  `render_mode: static`, `crawl_delay_ms: 20`, `respect_robots: true`,
  `seeds: [<base>/shop/cutting/]`, the listing template (EXIT_DISCOVERY's keys
  **minus `max_depth`** — the loader refuses it (2.3 review finding 10) and the
  domain default is already 5) and the product template
  (`LISTING_PATTERN`/`PRODUCT_PATTERN`; product extraction as 1.14's loader
  tests write it; listing extraction empty — ADR-0039 keeps listings out of
  the verdict).
- One worker process serves both runs in sequence: `load()` → run 1
  `completed` → `load()` the same YAML again → run 2 `completed`.
- Assert:
  - run 2 is a **new** run (`apply`'s `_START_RUN` is unconditional) whose
    queue, grouped by canonical path, **equals run 1's set** (the 44-row exit
    shape) — as fresh rows, with run 1's rows untouched (`done`, still under
    run 1's id);
  - every product page observed in run 1 has an observation in run 2 — the
    re-crawl re-observes, it does not skip;
  - run 2's product observations are `unchanged` lightweight rows (spec 003
    §4): the fixture is deterministic, so the content hash matches run 1's
    prior, which is looked up across runs. **If they are not, that is a
    defect to raise and fix in this slice, not a test to weaken.**
  - the domain stayed `active` throughout; the second `apply` versioned the
    templates (v1 → v2) and run 2's observations name the v2 ids (AGENTS rule
    12, ADR-0006).

### 3. Breadth-first, end to end — a cheap pin

In either crawl, map the fixture site's ordered `site.requests` to queue
`depth` and assert the sequence is non-decreasing. Valid for these fixtures
because every depth-1 URL is discovered from the seed's own page, so a
shallower row can never appear after a deeper claim. This pins that enqueue
and claim agree about `depth` through the real worker; the
`ORDER BY q2.depth, q2.id` itself is already mutation-pinned at adapter level
(1.8) and must not be re-derived here.

### Mutations that must be red (test agent proves, then restores)

1. `frontier.py` `_ENQUEUE`: drop `ON CONFLICT (run_id, url_hash) DO NOTHING`
   → the mega crawl's re-discoveries raise, rows retry to `failed`; acceptance
   1 red.
2. `frontier.py` `_ENQUEUE`: dedupe made cross-run — e.g. add
   `AND NOT EXISTS (SELECT 1 FROM crawl.crawl_queue q WHERE q.url_hash =
u.url_hash)` → run 2's seed still lands (the loader's own `_ENQUEUE`
   inserted it) but discovery adds nothing, and run 2 completes with one row.
   **This is why acceptance 2 asserts set equality, not just "run 2
   completed"** — a completed one-row run is exactly what the cross-run mutant
   produces.
3. Keep green, do not duplicate:
   `test_frontier.py::test_enqueue_deduplicates_within_a_run_but_not_across_runs`
   and `test_enqueue_guard.py`'s duplicate-spelling test already pin the
   adapter level.

## Decided (planner)

Verified on `develop` @ `4bbf3d9`, clean tree:

- **The constraint exists since 1.1**:
  `8c1d4a9f5e02_crawl_schema.py` line 215,
  `sa.UniqueConstraint("run_id", "url_hash")` on `crawl_queue`.
- **Both enqueues dedupe**: `frontier.py` `_ENQUEUE` (line 253) and
  `configuration.py` `_ENQUEUE` (line 100) carry
  `ON CONFLICT (run_id, url_hash) DO NOTHING` (the frontier's since 2.3 review
  finding 1).
- **Breadth-first is implemented and pinned at adapter level**:
  `ORDER BY q2.depth, q2.id` (frontier.py:87),
  `test_depth_orders_before_id_so_listings_drain_first` and
  `test_enqueued_rows_are_claimable_with_their_depth` (test_frontier.py:139,
  495); mutations were run in 1.8.
- **Correction to the prior session's assessment:** cross-run re-enqueue **is**
  pinned at adapter level —
  `test_enqueue_deduplicates_within_a_run_but_not_across_runs`
  (test_frontier.py:475) seeds a second run by SQL and asserts a fresh row.
  What is missing is the same property through the real run-creation path and
  the real worker: acceptance 2.
- **The 2.3 exit crawl never exercises the queue constraint.** Its 44 rows:
  1 seed + 9 listing rows (discs base + `?page=2` + `?page=3`, blades,
  `/shop/deep/1..5`) + 34 product rows (discs' 25 plain spellings, blades' 8
  context spellings, the seed page's featured `/shop/p/HT-SB-001`) — every URL
  discovered exactly once. The 33-distinct-pages number is the **pages**
  constraint (`UNIQUE (domain_id, url_hash)` plus rel=canonical), not the
  queue's. Hence the mega rule in acceptance 1.
- **The canonical pair is two queue rows on purpose.** `rel="canonical"` is
  page content; the queue hashes the lexical canonical URL, so the featured
  spelling and a context spelling enqueue separately, fetch separately, and
  collapse to one page row. Inherent to HTTP and settled in 2.2 — nobody
  should "fix" this by dropping a spelling before fetch.
- **BUILD_PLAN 2.4's "listings drained before products" is spec 002 §1's
  `ORDER BY depth, id`**, whose effect is that listings (shallow) drain before
  the products they fan out into. No conflict to reconcile; the wording
  describes the effect.
- **`apply` is the honest re-crawl path**: it starts a new run per invocation,
  seeds at depth 0, leaves an `active` domain active with its politeness
  state, and versions the templates — exactly what an operator's second
  `make load` does. 2.3's smoke already drove one run this way (44 rows
  through a scratch YAML); acceptance 2 pins it as a test.
- **No ADR needed.** Nothing here changes a structural decision; 0002
  (Postgres is the queue) and 0006 (template versioning) already cover the
  shapes this slice proves.

## Files this slice owns

- backend/tests/** (test-writer; expected: a new
  `tests/scheduler/test_dedupe_recrawl.py`, the `discovery=` extension of
  `seed_halden` in `tests/scheduler/test_link_discovery.py`, and additions to
  `tests/adapters/postgres/` only if needed)
- docs/BUILD_PLAN.md (tick — added by the integrator in the PR)
- Conditional, only if the pin finds a defect:
  backend/spydra/adapters/postgres/frontier.py,
  backend/spydra/adapters/postgres/configuration.py,
  backend/spydra/scheduler/crawl.py, backend/spydra/load.py

## Acceptance (BUILD_PLAN 2.4, spec 001 §1, spec 004 §1 rule 6)

- [x] The same URL discovered from two different listing pages in one run
      enqueues once — the mega crawl completes with every row `done`, every
      category exactly once, all 64 products observed (acceptance 1).
- [x] A later run enqueues the same URLs again: both runs through
      `PostgresConfiguration.apply`, run 2's queue set equals run 1's as fresh
      rows, every product page re-observed (acceptance 2).
- [x] Run 2's product observations are `unchanged` rows against run 1's
      priors; if not, the defect is fixed in-slice.
- [x] The second `apply` versions the templates and run 2's observations name
      the v2 ids (ADR-0006).
- [x] The crawl's request sequence is non-decreasing in depth (acceptance 3).
- [x] Mutations 1 and 2 proven red; the adapter-level dedupe tests stay green
      and unduplicated.
- [ ] `make check` green. — every leg green on this machine except
      `test-render`, which fails pre-existing and environmental (details in
      the handoff log); expected green in CI. Left for the integrator to
      tick from CI.

## Handoff log

- planner (subagent session): contract and decisions above; verified the
  mechanism end to end on `develop` @ `4bbf3d9`. Hand off to **spydra-test**
  (first file: `backend/tests/scheduler/test_dedupe_recrawl.py`); **spydra-
  backend** joins only if a defect surfaces.
- test (subagent session, on `feat/2.4-dedupe-recrawl` @ `54c5931`):
  - **Files.** New `backend/tests/scheduler/test_dedupe_recrawl.py`
    (2 tests). `seed_halden` in `test_link_discovery.py` extended with a
    `discovery=` keyword (default `EXIT_DISCOVERY`); not forked —
    `test_enqueue_guard.py`'s import unchanged and green.
  - **Row counts: the constants and the arithmetic agree.** The mega shape
    is exactly 84 (11 categories + 3 pagination + 5 deep + 64 product
    spellings + the featured spelling) and the exit shape 44, both derived
    in `expected_queue()` from `catalogue.NODES`/`LEAVES`/`PER_PAGE`, so the
    tests assert sets, never literals.
  - **No defect found.** Run 2's product observations are all `unchanged`
    lightweight rows (hash kept, `title`/`price_amount` NULL,
    `empty_extraction` false) against run 1's priors, under v2 templates, on
    the first run of the tests — nothing needed the in-slice fix.
  - **Mutations** (applied, run, restored with `git checkout`, re-run green):
    1. `frontier.py` `_ENQUEUE`, `ON CONFLICT (run_id, url_hash) DO NOTHING`
       dropped → mega test RED in 2.3 s: `assert {'failed'} == {'done'}` —
       the re-discoveries raise, rows retry to `failed`.
    2. same statement, `AND NOT EXISTS (SELECT 1 FROM crawl.crawl_queue q
WHERE q.url_hash = u.url_hash)` added → re-crawl test RED in 24 s:
       run 2 "completed" with queue set `{'/shop/cutting'}` — the one-row
       cross-run signature; the set-equality assertion is what catches it.
    3. (test agent's own) prior lookup made run-scoped — `_LATEST` in
       `observations.py` + `latest()` + the `writer.py` call site given
       `run_id` → re-crawl test RED in 46 s: "run 2 re-hashed instead of
       comparing". Pins that the prior of spec 003 §4 is cross-run.
    4. (validation, stayed green by design) claim `ORDER BY q2.depth, q2.id`
       → `ORDER BY q2.id` → mega test still GREEN: in these fixtures every
       depth-1 URL is discovered from the seed's single first claim, so id
       order coincides with depth order. Confirms the contract's "must not
       be re-derived here" — the SQL is pinned at adapter level (1.8).
  - **Adapter level stays green and unduplicated**: `test_frontier.py` +
    `test_enqueue_guard.py` + `test_catalogue.py` ran green alongside the
    new file (35 passed).
  - **Suite.** `make test-api`: **1047 passed, 2 skipped** (both skips
    pre-existing: `test_required_is_inert` annotation check, migration
    baseline). `make lint` green (ruff + mypy --strict + eslint + prettier).
  - **`make check` — one leg red, pre-existing, environmental.**
    `test-render`'s "no internal service name resolves from inside the
    render container" fails because `web` resolves to **127.0.53.53**
    (ICANN's name-collision sinkhole) via this machine's upstream DNS;
    `api`/`db`/`bff`/`edge` correctly ENOTFOUND from the same container.
    Reproduced identically with this slice's changes stashed, so it is not
    ours; expected green in CI (Linux compose DNS rejects the name).
  - **Environment fixes the next agent should know about** (both pre-existing
    states of this machine, not slice defects): the shared `venv` volume was
    missing `ruamel-yaml` (stale since before 1.14) — `docker compose run
--rm --no-deps api uv sync --frozen` resynced it; and the **dev**
    database was behind head (missing `configured_crawl_delay_ms`,
    `ix_page_observations_run_page`, `uq_unknown_pages_open`), which made
    `make generated-check` produce a stale `crawl.generated.ts` — `make
migrate` against dev brought it to head and the check now passes with no
    diff.
  - Hand off to **spydra-reviewer**.
- integrator (post-review, on `feat/2.4-dedupe-recrawl` @ `648e2c7`):
  - **Provenance note.** The parent session's reviewer output was not
    recorded anywhere before it ended, and this integrator session could
    not spawn a nested `spydra-reviewer` (subagent depth limit). The review
    below was therefore performed by the integrator in a fresh context that
    wrote none of the slice — a weaker separation than the house reviewer;
    the human should read the diff's three files with that in mind.
  - **Verdict: ready.** No blocking findings. Diff scope verified: exactly
    the three declared files, zero under `backend/spydra/`; `seed_halden`'s
    `discovery=` keyword is additive with the old default and
    `test_enqueue_guard.py`'s import is untouched; subjects ≤ 72 chars and
    house-shaped (`test: acceptance tests for …` matches 2.2/2.3).
  - **Not fixed, documented** — two non-blocking findings:
    1. _Degenerate-prior path unguarded._ The re-crawl test never asserts
       run 1's product observations are full rows (`title`/`price_amount`
       present, `unchanged` false); run 2's `unchanged` compares hashes
       against run 1's priors, so a hypothetical regression that emptied
       run 1's extraction would leave run 2 "unchanged" against degenerate
       priors and green. Non-blocking: extraction is pinned by the
       1.10/1.11 suites and the cross-run comparison itself is
       mutation-pinned.
    2. _`_yaml` hand-copies the exit discovery rule._ The listing
       template's `discovery` block re-states `EXIT_DISCOVERY`'s selectors
       and `deny_patterns` as literals instead of deriving from the
       constant the way `expected_queue` derives from the catalogue.
       Shape-affecting drift fails red on set equality, but shape-neutral
       drift (e.g. a broadened `deny_patterns`) would change what the
       re-crawl crawls without failing anything.
  - **Gate legs, run individually:** `lint`, `types`, `generated` (clean
    tree after), `test-api` (1047 passed, 2 skipped), `test-bff`, `test-web`
    — all green. `test-render` red with the documented DNS failure
    (`web` → 127.0.53.53, ICANN's name-collision sinkhole); proven
    pre-existing by re-running on `develop` @ `4bbf3d9` — identical
    assertion (`AssertionError: Missing expected rejection: web resolves
from the render container…`). Pushed with `--no-verify` under
    WORKFLOW.md §2; declared in the PR body.

## Open questions — for the human

Carried from 2.3:

1. Subdomains are never followed (the same-host rule); "subdomains
   configurable" needs a column and the public suffix list.
2. Listings whose links need JavaScript discover nothing on AUTO (ADR-0039's
   stated cost).
3. An invalid discovery pattern or selector in a hand-edited row raises
   mid-crawl; phase 3's authoring path should validate both.

None new.
