# feat/2.1-fixture-shapes

**Task:** BUILD_PLAN 2.1 · **Spec:** 004 §1–§5, TESTING.md §1/§4 ·
**ADRs that constrain this:** AGENTS.md rule 2 (hand-written fixtures), rule
14 (no network), 0028.

Stacked on `fix/2.0-phase1-decisions` (#21).

## Contract

Grow 1.4's fixture site with **one generated catalogue on one invented host
(`halden.test`)** that carries every discovery shape phase 2 needs. 2.2–2.10
and the phase-2 exit test against it, so it is built once, here, and is
exact: the full product set is a known list.

**Hand-written, then parameterised**, like `/generated/<n>`: two committed
HTML templates (`pages/halden/listing.html`, `pages/halden/product.html`)
written by hand, and a small catalogue table in
`backend/tests/fixtures/catalogue.py` (pure data plus rendering, stdlib
only). `server.py` routes the `/shop/` prefix to it, beside `TRAP_PREFIX`.
No captured markup.

### The catalogue

- **Tree:** `/shop/` (root) → 3 categories → 2 subcategories each, and one
  subcategory has a child of its own (the **subcategory nest**, depth 3).
  Leaves hold products.
- **Products:** a fixed, known number (tens, not thousands), every SKU
  distinct. Canonical product URL `/shop/p/<sku>`. Product pages extract with
  a selector template (title, price with currency, sku, images), like the
  vantage markup.
  `catalogue.PRODUCTS` (or equivalent) is the list the phase-2 exit asserts
  equality against.
- **Pagination:** leaves list 10 per page via `?page=N`, with
  `a[rel="next"]` and numbered page links; the last page has no next. At
  least one leaf spans 3+ pages.
- **Facets (the explosion):** every listing page carries facet links
  (`colour`, `grit`, `sort`, `per_page`) that **add to the current query**,
  so following them reaches every combination and each faceted page links to
  more. The reachable space must exceed spec 004 §3's 20,000-URL default cap
  on its own. Faceted pages list the same products (a filter that changes
  nothing is the real-world shape, and it is what makes a facet trap look
  legitimate).
- **Mega-menu:** every page (listing and product) carries a `nav.mega`
  linking the **entire** category tree. Category pages also carry their own
  scoped subcategory tiles in a separate container (`section.subcategories`).
  A `nav a` subcategory rule therefore discovers the whole tree from depth 0;
  a `section.subcategories a` rule discovers only the children.
- **Hidden subcategories (spec 004 §3a case A):** one category renders its
  subcategory tiles inside a `display:none` container. Static HTML, no JS.
- **Canonical:** at least one product is also reachable at a
  category-context URL (`/shop/<cat>/<sub>/p/<sku>`) whose page carries
  `<link rel="canonical" href="/shop/p/<sku>">` (same host, two URLs, one
  page). One page carries a canonical pointing **off-host**, which 2.2 must
  ignore.
- **Canonicalisation material (2.2):** listing links that carry `utm_*`,
  `gclid`, `ref`, a fragment, an unsorted query, `./`/`../` segments, a
  duplicate slash, a trailing slash, and an absolute same-host link with an
  upper-case host and the default port spelled out (built from the request's
  `Host`). A meaningful `?page=2` must stay meaningful.
- **Rejects (2.3, 2.5):** off-host links (`https://elsewhere.test/…`), a
  subdomain link (`https://cdn.halden.test/…`), `mailto:`, `tel:`,
  `javascript:`, a URL over 2,000 characters, a calendar path
  (`/shop/news/2026/10/`), and a relative-link bug that repeats a path
  segment pair for ever (`…/loop/x/loop/x/…`).
- **Depth:** a chain of listing pages deep enough that a `max_depth = 5`
  crawl from the root provably stops before something reachable at depth 6.
- **The trap:** 1.4's `/trap/` stays (unbounded, linear). The facet space and
  the repeating relative link are two more traps of different shapes; all
  three must be genuinely unbounded.
- **robots:** `halden.test` answers with the permissive robots file.

### Not in this slice

No crawler code. Nothing under `backend/spydra/`. No CSV seed file (2.9 owns
its fixtures) unless trivially useful.

## Files this slice owns

- backend/tests/fixtures/catalogue.py (new)
- backend/tests/fixtures/pages/halden/{listing,product}.html (new)
- backend/tests/fixtures/server.py (route the prefix)
- backend/tests/fixtures/README.md
- backend/tests/test_fixture_site.py (or a new `test_catalogue.py`)
- docs/BUILD_PLAN.md (tick)

## Acceptance

- [ ] Each shape above has a page, reachable over `FixtureSite` and pinned by
      a test that reads the served HTML (not the Python table).
- [ ] The product set is exact: a BFS over product/next/subcategory links
      (scoped tiles, facets ignored) from `/shop/` reaches exactly
      `PRODUCTS`, through the server.
- [ ] Facet space: a BFS following facet links exceeds 20,000 distinct URLs
      (stop the test at 20,001; it must not run out first).
- [ ] The repeating relative link and `/trap/` both keep producing new URLs
      to a depth well past any cap (e.g. 50).
- [ ] The mega-menu on a leaf product page links every category node; the
      scoped container on a category page links only its children.
- [ ] The hidden-tiles category's links are in the HTML inside a
      `display:none` container.
- [ ] Canonical pair: both URLs serve 200 and name the same canonical href.
- [ ] Deterministic: two fetches of any page are byte-identical.
- [ ] No route reaches the public internet; `make check` green.
- [ ] Mutation: break each shape in the catalogue (cap the facets, bound the
      loop, drop a product from the tree, drop the hidden style, scope the
      mega-menu) and the test pinning it goes red.

## Handoff log

- planner (main session): contract above, from spec 004 §1–§5 and
  BUILD_PLAN 2.2–2.10's "Done when" lines, so later tasks do not need to grow
  the site again.
- backend (main session; fixture infrastructure, no production code):
  `catalogue.py` + `pages/halden/{listing,product}.html`; `server.py` routes
  `/shop` to it before `ROUTES`. 64 products in 7 leaves (discs 25 → 3
  pages), 11 tree nodes. Deep chain hangs off the root's tiles
  (`/shop/deep/1/`…`/8/`, no products, so the product BFS is unaffected).
  `server.py` imports `catalogue` as `tests.fixtures.catalogue`, falling back
  to a bare import when the render suite runs it as `python3 server.py` from
  `/fixtures` (checked in the render container: `/shop/p/HT-CD-001` serves).
  Lint and mypy clean.

## Open questions — for the human

Carried from `fix/2.0-phase1-decisions` (see that file).

New:

1. **`DiscoveryRules` has no `max_depth`** (it lives on `Domain`), while
   spec 004 §1's JSON puts it on the template's discovery rules. 2.3 decides;
   noted here because the fixture's depth chain assumes the domain's 5.
