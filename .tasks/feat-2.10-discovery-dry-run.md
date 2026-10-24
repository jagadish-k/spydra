# feat/2.10-discovery-dry-run

**Task:** BUILD_PLAN 2.10 · **Spec:** 004 §4 (the report), §3a ("Prefer the
path already in the crawl" — the projection's use), §5 (two items' second
halves); 002 §5 (robots, applied to a non-run) · **ADRs:** none new — see
Decided (planner) for the verification; constraining: 0004 (honest UA, and
this is deliberately _not_ its pause path), 0008 (ports), 0019 (one
implementation — the dry-run shares `discover`, by analogy), 0039 (AUTO
gives listings no rendered second chance — the dry-run inherits it), 0040
(the cap whose breach the dry-run exists to prevent)

Stacked on `feat/2.9-csv-seeds` (PR pending).

## Contract

**One async library function fetches exactly one listing page and returns
what a crawl from it would enqueue, grouped by rule, with every judgement
call visible — and it cannot write anything, by construction.** No FastAPI,
no BFF, no DB: the seeds screen (3.13) and the review screen (3.14) call it
through the API later; today's callers are tests.

- `spydra/discovery/dry_run.py` (new):
  `async def dry_run(page_url, rules, *, static, page, host, user_agent,
max_depth=5, domain_deny=(), respect_robots=True) -> DryRunReport`.
  - `static: Fetcher` fetches `/robots.txt` — mirroring the worker's
    `RobotsCache(static)`; rendering a text file through Playwright would be
    absurd. `page: Fetcher` fetches the page, **already resolved by the
    caller per the domain's `render_mode` via `Fetchers.for_mode`** — the
    same composition point the worker uses, so the dry-run never learns
    about render modes (and `discovery/` never imports `scheduler/`).
  - Robots: a fresh per-call `RobotsCache(static)`; `rules_for` reuses the
    fail-closed / unrestricted / parse logic verbatim (`run_id=0` — the
    key is cache identity only, and the cache dies with the call, so it is
    one robots fetch per dry-run).
  - The one page fetch: `FetchRequest(url=page_url, user_agent=user_agent)`
    — the honest UA is required by the port, not optional here. Discover
    runs on `fetched.final_url` as `depth=0` (the page is a seed; links.py:
    "the URL the body was served from").
  - `DryRunReport` (frozen, slots): `matched: Mapping[str, RuleMatch]`
    (`RuleMatch(count, sample)` — the first `_SAMPLES` accepted URLs,
    fetchable spellings), `rejected: Mapping[str, Rejected]` — `discover`'s
    tally verbatim, already keyed `off_host` / `deny_pattern:<pattern>` per
    spec 004 §4; `mega_menu: MegaMenuFinding | None` — `whole_tree(discovery)`
    called on the **full** discovery before samples are capped;
    `projected_urls_at_max_depth: int`; `fetch_path: FetchPath`;
    `http_status: int | None`; `final_url: str`;
    `notices: tuple[str, ...]` of tokens.
  - Notices (tokens, 2.9's style — 3.13/3.14 map them to copy):
    `robots_disallowed` and `robots_unavailable` (fail-closed per spec 002
    §5 — the crawl would refuse the domain; the dry-run reports that
    instead of fetching, so it **never silently reports zero**),
    `fetch_failed`, `non_200` (rules on a 403 body are garbage — no
    discover), and `zero_links_static` — a 200 served by the STATIC path
    whose discovery accepted **zero** links: the ambiguous case, where the
    operator cannot otherwise tell a broken selector from a JS-dependent
    listing. Not fired for a rendered fetch: zero links in fully rendered
    HTML is an unambiguous broken selector.

### The projection — what the number is (pinned)

`projected_urls_at_max_depth` is a **deterministic arithmetic estimate of
the URLs a crawl from this one page would enqueue through `max_depth`** —
the multiplicative fan-out model. It is not a count of known URLs, not a
set, and it cannot see dedupe or the site's closure: those live on pages it
did not fetch. Options (b) URL-space closure (degenerate — no information
beyond page 1) and (c) a bounded recursive fetch to depth 5 (that is a
crawl; spec 004 §4 says one page) were weighed and rejected.

**Formula.** From the page's own `matched` counts: `p` = product links,
`n` = next-page links, `s` = subcategory links; `t = p + n + s` (total
fan-out), `f = n + s` (fan-out into pages that expand further). The seed is
a listing at depth 0; each listing at depth `k < D` contributes `t` URLs at
`k+1`, of which `f` are listings (`L_k = f^k`, `L_0 = 1`); product links
are leaves — a product template discovers nothing (spec 001 §1's "empty is
legitimate and common", assumed as the model's one constant). With
`D = max_depth`:

```
projected = t · (f^D − 1) / (f − 1)    f > 1
projected = t · D                      f = 1
projected = t                          f = 0    (nothing expands)
```

Same inputs → same number, always. On Halden: `nav a` on `/shop/cutting/`
(`p=0, n=0, s=11` → `t=11, f=11, D=5`) projects ≈ 195k — the model says "if
every page yields 11 new listings, by depth 5 you visit ~195k URLs", which
is the hazard signal, not a prediction: the real crawl dedupes a finite
site down to its 11 categories. The discs leaf (`p=10, n=1, s=0` → `t=11,
f=1`) projects 55. That gap is the whole point.

**Can it serve §3a's with/without comparison?** Partly, and the spec is
amended to say which part. Count equality can **never** prove set equality —
the "menu is a shortcut, not new coverage" case has identical reachable
sets and different fan-outs, so the projections differ and the spec's
literal "if the two sets match, delete the rule" is undecidable from one
page (and always was). What the comparison decides safely, deterministically:
**a rule whose removal leaves the projection unchanged enqueues nothing the
other rules don't — delete it** (first-match attribution makes this exact:
links another rule already matched re-attribute, `t` is unchanged); a rule
whose removal lowers the projection adds volume, and whether that volume is
coverage or shortcut is the operator's call, informed by `mega_menu` and
the samples. Spec 004 §3a's check is reworded to that; §4's key is renamed
`projected_urls_at_depth_5` → `projected_urls_at_max_depth` (the old name
lies whenever the domain's `max_depth` ≠ 5; nothing consumes the key yet —
this is the last moment to name it right) and its semantics paragraph is
added: estimate, formula inputs (`p`, `n`, `s` are the report's own matched
counts), the leaf assumption, and "cannot see dedupe or closure".

### Fetch and politeness posture (pinned)

- **One page fetch, always** — operator-triggered, pre-run. Not through the
  per-domain Postgres gate: there is no run and no claimed row to gate, and
  a single request has no in-process concurrency partner. The gate's job is
  serialising claim loops. The residual risk — landing inside a running
  crawl's `crawl_delay_ms` gap on the same host — is accepted for a
  one-shot operator action. 6.4's inspect-cache takes a politeness lock on
  misses; that is a repeatable automated surface, and its rule stays that
  feature's concern, not imported here.
- **render_mode**: the caller resolves `page` per the domain — static for
  STATIC, the sidecar for RENDERED, and AUTO resolves to `AutoFetcher`,
  whose `fetch()` is static-first. **AUTO listings get no rendered second
  chance** (ADR-0039): the dry-run previews the crawl, and the crawl on AUTO
  discovers nothing from a JS-dependent listing — so the dry-run reports
  zero, loudly (`zero_links_static`), rather than rendering what the crawl
  would never fetch. Rendering it would approve rules the crawl applies
  differently — exactly the drift `links.py`'s docstring (after ADR-0019)
  says a second implementation causes. This closes 2.3's open question 2
  for the dry-run: report, don't render.
- **robots: fetch and check, not trust-but-log.** One extra request, reusing
  `RobotsCache` verbatim. A dry-run that ignored robots would preview a
  crawl that will not happen — the crawl honours robots, so the preview
  honours them too, and `Disallow` for the configured UA, fail-closed 5xx,
  and `respect_robots = false` (unrestricted, logged — the cache already
  logs it) all behave exactly as in a run. The report carries the outcome
  as a notice; a disallowed page means zero page requests, asserted.

### No writes, asserted (pinned reading)

"Provably writes nothing" is achieved **by construction**: `dry_run`'s
signature contains no engine, connection, repository or frontier — it takes
ports (`Fetcher`) and returns data, and the module imports nothing from
`adapters/postgres` or anywhere a write could live. The tests make the
construction claim checkable: an import test pins the module's imports (2.9's
AST allowlist pattern, scoped to this module); a counting fetcher asserts
the fixture site saw **exactly one page request** (and exactly one robots
request when `respect_robots=True`); and a real-engine test asserts the
database saw **zero rows** — queue, pages, observations, runs all unchanged.

## Decided (user)

- None this slice. Every judgement call was resolvable from spec 004 §4,
  §3a, spec 002 §5 and existing ADRs; the two that shape behaviour — the
  projection's estimate semantics and the one-fetch/robots posture — are
  planner decisions pinned above and written into spec 004, where 2.6 put
  its decisions for the same reason.

## Decided (planner)

- **The projection is an estimate, and the spec now says so** (formula and
  honesty above). The example number stays an example of the estimate, and
  the §3a check is downgraded from set equality — unknowable from one page —
  to the projection comparison, which is deterministic and conservative in
  the right direction: it can only recommend deleting a rule that provably
  enqueues nothing.
- **Key renamed to `projected_urls_at_max_depth`** while nothing consumes
  it. BUILD_PLAN 2.6's Done text and 2.6's task file keep the old spelling —
  historical records, not touched; spec 004 is the live contract.
- **The dry-run shares everything shareable**: `discover` (the engine),
  `whole_tree` (the finding), `Rejected` (the tally shape), `_SAMPLES` (the
  sample cap), `RobotsCache` (robots), `Fetchers.for_mode` (render_mode,
  at the caller). New code in this slice is one module of orchestration and
  one report dataclass — a second discovery implementation would be the
  ADR-0019 defect by analogy.
- **Report samples are absolute fetchable URLs**, not the spec example's
  relative paths — an operator must be able to open one. The spec's JSON
  stays illustrative of shape; §4's example gains the new keys
  (`mega_menu`, `fetch_path`, `http_status`, `notices`) so 3.13/3.14 build
  against the real report.
- **`discovery/` gains its one impure member.** `links.py`, `mega_menu.py`
  and `canonical.py` are pure; `dry_run.py` talks to the `Fetcher` **port**
  (never an adapter) and to nothing else. The alternative — putting it in
  `scheduler/`, the claim-loop world — would hide it from the screens'
  backend callers and still need `discovery` imports. Named in the module
  docstring.
- **`depth=0` is fixed, not a parameter** — the page is a seed; that is
  what both screens mean by it.
- **No ADR.** Verified: no new dependency, no datastore or service boundary,
  no public API shape (library-internal until 3.x wires an endpoint, which
  follows the existing router pattern), no ownership change. The decisions
  live in spec 004 — the same home 2.6 chose for its mega-menu paragraph.
  If a later slice wants the projection or the mega-menu finding to _block_
  approval rather than advise, that changes the authoring pipeline's
  contract and gets its ADR then (2.6's open question 1, unchanged).

## Files this slice owns

- backend/spydra/discovery/dry_run.py (new)
- backend/tests/discovery/test_dry_run.py (new, test-writer)
- docs/specs/004-discovery.md (§4: key rename, semantics paragraph, example
  keys; §3a: the comparison rewording)
- .tasks/feat-2.10-discovery-dry-run.md

Explicitly **not** touched: `discovery/links.py` and `discovery/mega_menu.py`
(2.3/2.5/2.6's; consumed as-is), `tests/fixtures/catalogue.py` and
`pages/halden/` (2.1's; every shape needed exists), `scheduler/` (the
caller-side `Fetchers.for_mode` convention is documented here, changed
nowhere), `docs/BUILD_PLAN.md` (integrator ticks 2.10 in the PR).

## Acceptance (BUILD_PLAN 2.10, spec 004 §5)

- [ ] Counts per rule against 2.1's fixtures: `dry_run` over the fixture
      site reports per-rule `matched` counts equal to the catalogue
      constants for that page — e.g. `/shop/cutting/discs/` with
      `EXIT_DISCOVERY`: products = `PER_PAGE` (page 1 of the leaf's set),
      `next_page` = 1, tiles per the page's own container; `/shop/cutting/`:
      the three tile links. Derived from `catalogue.py`, no magic numbers.
- [ ] The facet trap's second half (spec 004 §5: "the dry-run reports the
      rejected count"): on a faceted leaf page, `rejected` carries
      `deny_pattern:[?&](colour|grit|sort|view|per_page)=` with the page's
      facet-link count and samples — 2.5's reasons surface unchanged.
- [ ] Mega-menu wiring (spec 004 §5: "caught by the dry-run"): `dry_run`
      with `subcategory_links: "nav a"` on `/shop/cutting/` returns the
      `whole_tree` finding in the report — 11 links, 3 branches, deepest
      chain 3 — and the scoped rule over the same page returns
      `mega_menu=None`. This is 2.6's flag reaching the report it was
      shaped for.
- [ ] The projection: deterministic (same inputs, same number), the three
      closed-form branches exercised (`f > 1`, `f = 1`, `f = 0`), the
      `nav a` case ≈ 195k vs the scoped case small, and the §3a comparison
      demonstrated both ways on the fixture — removing a redundant rule
      leaves the projection unchanged (the re-attribution case:
      `product_links: "nav.mega a"` + `subcategory_links: "nav a"`, unset
      the subcategory rule, projection identical → the amended check says
      delete), removing a load-bearing one lowers it.
- [ ] Writes nothing, three ways: the module's imports pinned by test (no
      `adapters.postgres`, no engine); a counting fetcher sees exactly one
      page request (one robots request when `respect_robots=True`; zero
      robots requests when false); a real-engine test sees zero rows in
      `crawl_queue`, `pages`, `page_observations` and `runs` after a call.
- [ ] Robots posture: a disallowing robots.txt → `robots_disallowed`
      notice, zero page requests; a 5xx robots → `robots_unavailable`
      notice, zero page requests; `respect_robots=False` → no robots
      fetch, page fetched.
- [ ] The loud zero: a 200 via the STATIC path with zero accepted links →
      `zero_links_static` notice; the same page with links accepted → no
      notice. A RENDERED-path fetch reporting zero carries no notice.
- [ ] Report shape matches spec 004 §4's keys: `matched` per rule with
      `count` + `sample`, `rejected` keyed `off_host` /
      `deny_pattern:<pattern>` with `pattern`, the mega-menu finding, the
      projection, `fetch_path`, `http_status`, `notices`.
- [ ] `make check` green. Named mutations: the formula's `t`/`f` swapped,
      the `f = 1` branch deleted (falls into the geometric form), sample
      cap changed, `whole_tree` called after samples are capped (the
      finding's link count drops), robots check skipped (disallowed page
      still fetched — the request-count assert fires), the `zero_links`
      notice inverted.

## Handoff log

- planner — contract and decisions above; branch cut from the tip of
  `feat/2.9-csv-seeds`. Verified no in-flight slice owns `discovery/`
  (the stack is sequential: 2.6's spec-004 paragraph is in this branch's
  tree). Fixture situation verified: `nav a`'s 11/3/3 finding, the
  facet form, `PER_PAGE`, tiles and `EXIT_DISCOVERY` all shipped in 2.1;
  `RobotsCache`, `Fetchers.for_mode` and `Rejected` are all reusable
  as-is. First file for the implementer:
  `backend/spydra/discovery/dry_run.py`. To **spydra-backend**.
- backend — `discovery/dry_run.py` built to the contract: robots first
  through a fresh per-call `RobotsCache(static)` (`run_id=0`, cache dies
  with the call; disallow and fail-closed → notice + **zero** page
  requests), the one page fetch through the caller-resolved `page`
  fetcher, `discover` on `fetched.final_url` at `depth=0`, `whole_tree`
  on the full discovery before any sample view exists, the three-branch
  projection (`f>1` geometric — exact integer division; `f=1` linear;
  `f=0` plain `t`), and the five notice tokens as module-level constants
  (`ROBOTS_DISALLOWED`, `ROBOTS_UNAVAILABLE`, `FETCH_FAILED`, `NON_200`,
  `ZERO_LINKS_STATIC`) so 3.13/3.14 import them instead of retyping
  strings. Empty-report edges: nothing fetched → `http_status=None`,
  `final_url=""`, `fetch_path=page.path` (the posture the operator
  configured, so the report still names it). Spec 004 §4 rewritten as
  built (example gains `mega_menu`/`fetch_path`/`http_status`/`notices`,
  samples absolute, rename line, estimate-semantics paragraph with the
  formula); §3a's check reworded to the projection comparison. Three
  deviations from the task file, none behavioural:
  1. **The `nav a` example projects 177,155, not "≈195k".** The task's
     own pinned formula gives `11·(11⁵−1)/10 = 177,155`; 195k is the
     output of no variant (with the seed row: 177,156). Verified by
     running it on the fixture site. The spec carries 177,155 — the
     formula is the pinned thing, and an example that fails its own
     arithmetic would be copied into screen copy.
  2. **"`discovery/` never imports `scheduler/`" is unsatisfiable as
     written**: `RobotsCache`, mandated for verbatim reuse three lines
     later, lives in `spydra/scheduler/robots.py`. Read as "never imports
     the claim-loop/render-mode world (`scheduler.crawl`)". The one
     scheduler import is `scheduler.robots`, which itself imports only
     domain + ports — no cycle (`scheduler.crawl` → `discovery.links`;
     `discovery.dry_run` → `scheduler.robots`). The test-writer's import
     allowlist needs `spydra.scheduler.robots` on it.
  3. **`Backpressure` propagates** rather than becoming a notice: the
     port contract says it is not a fetch failure and not the
     supplier's doing, and a dry-run has no row to requeue — the caller
     retries. The notice vocabulary stays the five tokens.
     `make lint` clean; `make test-api` green, 1256 collected — exactly the
     `required`-inertness parametrisation's one new case over 2.9's 1255.
     A throwaway smoke (deleted) confirmed against the fixture site: exit
     rules on `/shop/cutting/discs/` → products `PER_PAGE`, `next_page` 1,
     the facet `deny_pattern` tally present, projection 55; `nav a` on
     `/shop/cutting/` → the 11/3/3 finding and 177,155; the loud zero; a
     404 → `non_200` with no discovery; the §3a comparison both ways
     (re-attr: `nav.mega a`+`nav a` vs `nav.mega a` alone — 11 = 11, the
     amended check says delete; load-bearing: exit rules minus the
     subcategory rule — projection drops); exactly one page request and one
     robots request per call. To **spydra-test**.

## Open questions

1. **The dry-run's gap risk vs a running crawl** (Decided, accepted): one
   operator-triggered fetch can land inside a live crawl's politeness gap
   on the same host. Accepted because it is one shot and human-triggered;
   if 3.13/3.14 make dry-runs frequent or automated, revisit against 6.4's
   lock-on-miss rule then.
2. **A product template with discovery rules breaks the projection's leaf
   assumption** (the model's one constant): product links would expand and
   the estimate under-counts. Not defended — the assumption is stated in
   the spec's semantics paragraph, and a template set that puts discovery
   on product pages is rare enough that the report's per-rule counts still
   tell the operator what matched.
3. **2.3's open question 2 stands for the crawl itself**: this slice
   resolves it for the dry-run only (report loudly, don't render). Whether
   an AUTO _run_ should render a listing whose static discovery accepts
   zero is still open and is 3.x's call, with ADR-0039's current answer
   ("use `rendered`") unchanged.
