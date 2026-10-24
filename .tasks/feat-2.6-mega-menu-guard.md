# feat/2.6-mega-menu-guard

**Task:** BUILD_PLAN 2.6 · **Spec:** 004 §3a (all three cases + "Prefer the
path already in the crawl"), §4 (seam), §5 (two items) · **ADRs:** none new —
pure analysis, no dependency, no ownership change (reasoning in Decided)

Stacked on `feat/2.5-trap-defences` (PR pending, base #26).

## Contract

**A pure analysis that flags a `subcategory_links` rule discovering the whole
tree from one page, shaped as the library function 2.10's dry-run calls.**
Nothing scopes a rule at runtime; nothing is enqueued or rejected here. The
flag joins the dry-run report in 2.10 — this slice delivers the function and
its tests, so the "caught by the dry-run" acceptance resolves to _"the
analysis the dry-run will call returns the flag."_

- `spydra/discovery/mega_menu.py` (new, pure, stdlib + `domain.urls`):
  `whole_tree(discovery: Discovery) -> MegaMenuFinding | None`.
  Reads **only** `discovery.accepted["subcategory_links"]` (spec 004 §3a
  names that rule; a product rule matching a nav is a broken selector the
  count/sample report already exposes).

### The heuristic, pinned

1. Take `accepted["subcategory_links"]` — absent or empty → `None`.
2. Canonicalise each URL (`domain.urls.canonical_url`), keep the **path**
   (query dropped — tree structure never lives in the query), dedupe paths.
   Facet spellings and canonical pairs collapse to one node.
3. `P` is an **ancestor** of `Q` iff `P ≠ Q` and `Q == P + "/" + rest`
   (canonical paths carry no trailing slash, so the boundary is a segment;
   `/` is an ancestor of every other path).
4. A **branch root** is a path with no ancestor in the set. A root
   **spans** iff some other path in the set has it as an ancestor.
5. **Finding iff ≥ 2 roots span** (`_SPANNING_ROOTS = 2`, a named module
   constant whose docstring derives it from the two Halden shapes below).

`MegaMenuFinding` (frozen dataclass): `links` (accepted subcategory links),
`paths` (distinct canonical paths), `branches` (spanning roots), `levels`
(deepest ancestor→descendant chain, in nodes), `roots` (up to 3 spanning-root
paths — the sample an operator reads). The one-sentence operator explanation
2.10 will render: _"From this one page, this rule matched both a category and
its own subcategories under N separate branches — a site-wide menu's shape,
not one section's tiles; scope the selector to the menu's own container."_

### Why it fires and stays silent (derive the constant from these)

Halden's mega-menu (`nav.mega`, built by `catalogue._mega()`) links **all 11
category nodes on every page**. A `nav a` rule on `/shop/cutting/` (a
non-leaf page — `nav.pagination` is empty there, so `nav a` matches exactly
the 11 mega links) accepts 11 paths: three roots — `/shop/cutting`,
`/shop/grinding`, `/shop/finishing` — **and every one spans** (discs, blades;
wheels, belts→narrow, wide; pads, polish; deepest chain 3 nodes:
grinding → belts → narrow). 3 spanning roots ≥ 2 → **fires**.

The scoped counterexample on the **same page**: `section.subcategories`
tiles are one node's children only. On `/shop/cutting/`: discs, blades,
`/shop/deep/1` — three roots, **none spans** (no accepted path extends
another). On `/shop/grinding/belts/` (narrow, wide) and on `/shop/` (the
three top categories): same flat shape. Roots, never spanning → **silent**.
Counting plain roots instead of _spanning_ roots would fire on every scoped
tile set with two children — that inversion is the mutation this slice
exists to catch.

Silent too: `EXIT_DISCOVERY` (`section.subcategories a, form.facets a`) on
`EXIT_SEED` — tiles + archive, no facets rendered on a non-leaf page. And
under a combined rule on a leaf page, facet URLs share one path with
different queries → path-dedupe collapses them to a single node, no nesting.

### Case A (`display:none`): pin it, build nothing

Spec §3a: selectolax parses markup and computes no styles, so a CSS-hidden
link is an ordinary match — "nothing needs building". **The fixture already
exists** (2.1, `catalogue.py`): `/shop/finishing/` (`hidden_tiles=True`)
serves `<section class="subcategories" style="display:none">` with pads and
polish inside; `test_catalogue.py` asserts exactly one such category. This
slice adds **no fixture** — it pins discovery of the existing one: `discover`
over `/shop/finishing/`'s static HTML with `subcategory_links: "section.subcategories a"`
accepts `/shop/finishing/pads` and `/shop/finishing/polish`, no reveal step.

## Decided (planner)

- **"Scoped to its container" is operator guidance, not a code mechanism.**
  Spec §3a's sentence tells the operator what a good selector looks like;
  no runtime scoping exists or is added. The code deliverable is detection
  only. Verified against the spec text and against 2.3's `discover` (rules
  are bare selectors; there is no scope parameter anywhere to hang a
  mechanism on).
- **The threshold is structural (≥ 2 spanning roots), not a link count.**
  A count threshold (`nav a` finds 11, tiles find 2–3) breaks the moment a
  supplier has 3 categories or a 40-tile section page. Branch-and-level
  structure is what separates "one container's tiles" from "the site tree",
  and it is what the one-sentence explanation actually describes.
- **Accepted links, not raw selector matches.** What the rule _enqueues_ is
  the hazard; if `allow_patterns` narrows a mega-menu to one branch, the
  rule no longer discovers the whole tree and the flag correctly stays
  silent. `Discovery` already carries the post-filter set, grouped per rule.
- **Single-branch site menus are the named boundary, not a miss.** A
  site-wide menu nested under one top-level branch stays silent here (one
  spanning root). That shape is §3a's "Prefer the path already in the
  crawl" comparison — `projected_urls_at_depth_5` with the rule set and
  unset, reachability rather than structure — which is 2.10's report. The
  seam: 2.10 calls `whole_tree(discovery)` for the structural flag and
  computes the projection for the reachability comparison; **this slice
  builds no projection.**
- **No ADR.** No new dependency, no datastore/service change, no public API
  shape change. The hazard and the container guidance are already spec 004
  §3a. If the flag ever needs to _block_ approval rather than advise, that
  changes the authoring pipeline's contract and gets its ADR then (open
  question 1).
- Spec 004 §4 gains one short paragraph naming the `whole_tree` finding,
  the function, and the projection seam — 2.10 owns the report's JSON keys.

## Files this slice owns

- backend/spydra/discovery/mega_menu.py (new)
- docs/specs/004-discovery.md (§4: the one paragraph named above)
- backend/tests/discovery/test_mega_menu.py (test-writer, new)
- .tasks/feat-2.6-mega-menu-guard.md

Explicitly **not** touched: `discovery/links.py` (2.3/2.5's; `Discovery`
already carries everything the analysis reads),
`tests/fixtures/catalogue.py` and `pages/halden/` (2.1's; the needed shapes
exist), `docs/BUILD_PLAN.md` (integrator ticks 2.6 in the PR, WORKFLOW §4).

## Acceptance (BUILD_PLAN 2.6, spec 004 §5)

- [x] `whole_tree` over `discover` of `/shop/cutting/`'s static HTML with
      `subcategory_links: "nav a"` returns the finding — 11 links, 3
      spanning branches, deepest chain 3 nodes. This is "a `nav a` rule on
      2.1's mega-menu fixture is caught by the dry-run" (spec 004 §5): the
      analysis the dry-run calls returns the flag; 2.10 wires the report.
- [x] The scoped rule over the **same page** stays silent:
      `section.subcategories a` on `/shop/cutting/` and on
      `/shop/grinding/belts/` (a page carrying both the mega-menu and the
      tiles) → no finding.
- [x] The production rule stays silent: `EXIT_DISCOVERY` on `EXIT_SEED`'s
      page → no finding.
- [x] `/shop/finishing/`'s `display:none` subcategory tiles are discovered
      by a static `discover` with no reveal step — pads and polish accepted
      (spec 004 §5).
- [x] Query spellings cannot fake a tree: facet URLs under a combined rule
      collapse to one node (paths deduped, query dropped).
- [x] Pure module: no I/O imports, not async, same answer twice (2.3's
      house style).
- [x] `make check` green. Named mutations: spanning → plain roots (must go
      red — it is the false positive this task exists to prevent),
      threshold 2 → 3 (killed by the two-branch allow test, not the mega
      case), ancestor test without the segment boundary, dedupe dropped,
      `levels` off by one, sample roots empty.

## Handoff log

- planner — contract and decisions above; branch cut from the tip of
  `feat/2.5-trap-defences`. Fixture situation verified: mega-menu (11 nodes
  on every page) and hidden tiles (`/shop/finishing/`) both shipped in 2.1;
  `tests/fixtures/README.md` already maps both shapes to 2.6. No in-flight
  slice owns `discovery/`. First file for the implementer:
  `backend/spydra/discovery/mega_menu.py`. To **spydra-backend**.
- spydra-backend — built `discovery/mega_menu.py` (pure, stdlib +
  `domain.urls` + `discovery.links.Discovery` for the type): `whole_tree`
  canonicalises accepted `subcategory_links`, keeps the path, dedupes to a
  set, and finds spanning roots by pairwise segment-boundary ancestry
  (`q.startswith(p + "/")`, `/` owning every other path — O(n²) slice
  comparisons, deliberate: per-page link sets are small and each helper is
  the contract's definition verbatim). `MegaMenuFinding(links, paths,
branches, levels, roots)` — first four are ints (the acceptance reads
  "11 links, 3 spanning branches, deepest chain 3 nodes"), `roots` is the
  up-to-3 sorted sample. `levels` is `1 + max ancestor count` — ancestors
  of one path nest (prefix forest), so the count is the chain. Spec 004 §4
  gained the one planned paragraph (flag, function, projection backstop).
  Decisions worth knowing:
  - **`links`/`paths`/`branches` are counts, `roots` carries paths.** The
    field list's parentheticals read two ways; "the link count" in the task
    and "11 links, 3 spanning branches" in the acceptance pin the ints.
    Redundancy of branches-as-tuple with roots-as-sample avoided.
  - **No re-export from `discovery/__init__.py`** — that file is a bare
    docstring; `links` and `canonical` are imported by full path
    (`spydra.discovery.links.discover` in spec 004 §1), so `mega_menu`
    follows. The spec paragraph names the full path too.
  - **No try/except around `canonical_url`.** Accepted links are
    post-canonicalisation by construction (`discover` rejects unparseable
    before accepting); handling it would guard an impossible state.
  - **`_ROOT_SAMPLE = 3` named alongside `_SPANNING_ROOTS`**, house style
    of `links._SAMPLES`.
    Smoke (throwaway, run in the api container, deleted): `nav a` on
    `/shop/cutting/` fires with exactly the pinned numbers; `section.subcategories`
    silent on `/shop/cutting/`, `/shop/grinding/belts/` (two roots, none
    spanning — the plain-roots mutation case), `/shop/`; `EXIT_DISCOVERY`
    silent on the exit seed; `/shop/finishing/` hidden tiles accepted
    statically; 16 facet spellings of one leaf path collapse to one node.
    Note for the test-writer: `discover` accepts **fetchable** spellings
    (trailing slash kept, query kept) — build expected paths through
    `canonical_url`, not `urlsplit(...).path`. To **spydra-test**.
- spydra-test — `backend/tests/discovery/test_mega_menu.py` (14 test items,
  `make check` green): every discovery through `discover` over the served
  fixture site; every expected number derived from `catalogue.py`
  (`len(NODES)` links/paths, `len(TREE)` branches, `LEVELS = 1 + max
ancestor count`, roots sample = sorted canonical top-category paths) — no
  magic numbers. Coverage beyond the checkboxes: the single-branch blind
  spot pinned as silent (`nav.mega a[href^="/shop/grinding"]` — one
  spanning root); an `allow_patterns` two-branch narrowing still fires with
  `branches == 2` (the Decided "allow narrows the hazard" bullet, both
  ways); a `product_links` rule matching the nav stays silent (reads only
  `subcategory_links`); the prefix boundary pinned by splicing
  `/shop/cutting-tools` and `/shop/grinding-tools` tiles into `/shop/`'s
  container — five flat roots, silent. Backend's two flagged calls handled:
  ints asserted against derived constants; expected paths built through
  `canonical_url`. Mutations (each applied, this suite run, restored —
  **all nine red**, restored green):
  1. spanning → plain roots — RED (scoped-tiles silence tests fire);
  2. `_SPANNING_ROOTS` 2 → 1 — RED (the single-branch pin fires);
  3. 2 → 3 — RED (the two-branch allow case goes silent). Note: on bare
     Halden `nav a` (3 branches) 2→3 is _equivalent_ — the task file's own
     "misses Halden's mega" wording has this wrong; the two-branch test is
     what makes the mutation provably non-equivalent;
  4. ancestor boundary → bare `startswith` — RED (the spliced `-tools`
     pair "spans");
  5. query-strip removed — RED (`test_query_spellings…`, paths 13 ≠ 11);
  6. dedupe dropped (set → list) — RED (same test);
  7. `levels` off by one — RED (nav-a levels);
  8. `roots` sample emptied — RED (roots assertion);
  9. rule key → `product_links` — RED (nav-a finding disappears; the
     product-rule test fires). One environmental note, not a defect: during
     the first full `make check`, `render`'s DNS-isolation test
     (`acceptance.test.js:316`) failed once with `web` resolving from the
     render container; it passes on the clean tree **and** with this diff
     on re-run (57/57 twice) — flaky when other compose containers are up,
     untouched by this slice. No production defects found. To
     **spydra-reviewer**.

- integrator (on `feat/2.6-mega-menu-guard` @ `322efaf`, base
  `feat/2.5-trap-defences`):
  - **Gate.** Legs run individually, all green: `make lint` 0 ·
    `make types` 0, clean tree · `make generated` 0, clean tree ·
    `make test-api` **1089 passed, 2 skipped** — 1091 collected =
    1076 at the 2.5 tip (verified by a worktree collect) + the 14
    authored items + one auto-parametrised case:
    `test_required_is_inert.py::…[mega_menu.py]` gains a parameter
    because a new production module appeared, so the count arithmetic
    closes exactly · `make test-bff` 0 fail · `make test-web` 10 pass ·
    **`make test-render` 57/57 green** — the DNS flake named in
    spydra-test's note did not appear, so no environmental declaration
    and no `--no-verify`: every leg passed and the push rode the gate.
  - **Scope.** `git diff --stat feat/2.5-trap-defences...HEAD`: exactly
    four files — `backend/spydra/discovery/mega_menu.py` (new),
    `backend/tests/discovery/test_mega_menu.py` (new),
    `docs/specs/004-discovery.md` (+10), this task file. Nothing
    outside; no findings. The untracked `.tasks/pr-2.5-body.md` (the
    2.5 slice's PR body) is not this slice's and was left uncommitted.
    Commit subjects imperative, ≤ 72 chars (the noun-phrase test
    subject matches 2.3/2.5 house style).
  - **BUILD_PLAN 2.6 ticked** — `**Done:**` line in the plan's density:
    prefix forest, ≥ 2 spanning roots, fires/silent pinned, Case A
    free, both blind spots named with 2.10's projection as backstop.
  - **PR handoff.** Pushed `feat/2.6-mega-menu-guard` (no
    `--no-verify` — all legs green). `gh` is not installed on this
    host, so the PR body is `.tasks/pr-2.6-body.md`; the human opens
    `feat/2.5-trap-defences...feat/2.6-mega-menu-guard`. **Stacked**:
    2.5 sits on PR #26 (`feat/2.4-dedupe-recrawl`) — merge #26, merge
    2.5's PR, then retarget this one to `develop` in turn. Not merged
    by the integrator.

## Open questions

1. Should the `whole_tree` flag ever _block_ template approval rather than
   advise in the dry-run report? Spec §3a reads as operator-judgement
   ("let `allow_patterns` and the dry-run confirm the count before
   approval"); a blocking mode changes the authoring pipeline's contract
   and would need an ADR. Not built.
2. The single-branch boundary (Decided) is deliberate: structural detection
   here, reachability projection in 2.10. Flagging it for the human because
   it is a chosen blind spot, not an accident — a one-branch catalogue's
   site-wide menu is invisible to this analysis until 2.10's projection
   lands.
3. Blind spot 2, the home link (reviewer, 2.6): one accepted link to an
   ancestor of everything else accepted — the site root, or Halden's
   `/shop/` from a breadcrumb — becomes the sole branch root, so the
   finding cannot fire there for the same broken rule that fires on pages
   without the home link. Real menus link Home. Named in `mega_menu.py`'s
   docstring beside the single-branch case; covered by the same 2.10
   `projected_urls_at_depth_5` backstop. Not fixed — a repair (set the
   sole universal ancestor aside when counting roots) is easy but
   unpinned against real menus, and this slice ships the named blind spot.

**Decided (human), 2026-10-24:** OQ1 (advise vs block) — explanation
requested 2026-10-24, decision pending.
