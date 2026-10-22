# Fixtures — the local site the crawler is proven against

BUILD_PLAN `1.4`. **Hand-written, never captured** (AGENTS.md rule 2,
TESTING.md §4): a fixture has to hold still for years, and a copy of a real
page goes stale, carries someone else's content, and tempts a test into
re-fetching the original.

One file per **shape** the extraction chain must handle. The host names are
invented — nothing here is a copy of a real page and a reader should not go
looking for the original.

| Page                                                   | Shape it exists to exercise                      |
| ------------------------------------------------------ | ------------------------------------------------ |
| `vantage-abrasives/product.html`                       | well-formed, selector path (spec 003 §2)         |
| `vantage-abrasives/listing.html`                       | product links + next page (spec 004 §1)          |
| `orbis-components/product-jsonld.html`                 | `schema.org/Product`, structured rung 1          |
| `orbis-components/product-stripped.html`               | the same page, JSON-LD removed → falls to rung 2 |
| `northfield/product-redesigned.html`                   | same URL, selectors no longer match → redesign   |
| `mertens/product-rendered.html`                        | content only after JavaScript (spec 012)         |
| `mertens/product-missing.html`                         | soft 404: HTTP 200, no product (ADR-0030)        |
| `mertens/product-dialog.html`                          | opens `alert()` before writing (spec 012 §3)     |
| `vantage-abrasives/product-images.html`                | 24 delayed images, for `block_resources`         |
| `vantage-abrasives/product-image-stub.html`            | image-only JSON-LD stub over `product.html` (B3) |
| `vantage-abrasives/product-image-stub-redesigned.html` | the same stub over a redesign (ADR-0037)         |
| `robots/*.txt`                                         | permissive · `Crawl-delay` · disallow-all        |

## Generated responses

BUILD_PLAN `1.5`. Three of spec 012 §6's criteria are about a response's
**timing** or **size** rather than its markup, and none of the three can be a
committed file: a response that stalls is a property of the server, and a
20 MB page is both unreviewable and refused by the pre-commit hook (> 2 MB).
So `server.py` synthesizes them, with the shape as a URL parameter.

| Path               | What it does                                                                                                                 |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `/slow/<ms>`       | sleeps, then a small product page — holds a render context open so the context cap and the 503 are observed, not inferred    |
| `/img/slow/<name>` | a 1x1 PNG behind a 150 ms delay — the delay is the whole mechanism behind "`block_resources` measurably reduces render time" |
| `/oversized/<mb>`  | `<mb>` MB of HTML as one text node, bounded at 32 MB so a typo cannot ask for 20 GB                                          |
| `/trap/…`          | unbounded link depth, for BUILD_PLAN `2.5`'s caps                                                                            |
| `/generated/<n>`   | product `<n>` of an unbounded catalogue, with a `Set-Cookie` — for spec 009 §5's 1,000-page log budget (BUILD_PLAN `1.13`)   |
| `/shop/…`          | Halden Tools, the discovery catalogue (`catalogue.py`, BUILD_PLAN `2.1`) — see below                                         |
| `/moved/…`         | redirects with a relative canonical, same-host and off-host (to `localhost:<port>`), for BUILD_PLAN `2.2` — see below        |

**`/moved/…` is two redirects for `2.2`.** The crawler follows redirects, so
`rel="canonical"` must resolve against the URL the body came from.
`/moved/listing` 301s to `/moved/listing/`, whose `href="p/1"` is
`/moved/listing/p/1` from the final URL and `/moved/p/1` from the requested
one. `/moved/away` 301s to the same server under another host name
(`localhost:<port>`), whose `/moved/landing` names itself as canonical. That
is a canonical on a host the domain does not own, so it must be ignored.

**`/generated/<n>` is `vantage-abrasives/product.html` with `<n>` written
into the title, SKU, price and image names**, so a thousand URLs are a
thousand distinct products that the one approved template extracts. A
thousand committed files would be one shape copied a thousand times. It sets
a session cookie on purpose: spec 009 §1 forbids logging credentials, and a
log test over a site that sends none would pass against a worker that dumps
every response header.

**The delay on the images is not incidental.** Served instantly, a 24-image
gallery renders at the same speed whether images are blocked or not, and
spec 012 §6's `block_resources` criterion becomes unfalsifiable.

**`vantage-abrasives/product-image-stub.html` is `product.html` plus a
`schema.org/Product` block whose only property is `image`.** Rung 1 finds a
Product and extracts one asset URL, which is nothing the content hash can
compare (spec 003 §4) and so an empty extraction (ADR-0037). With the
approved template the selector rung must still win; without one the stub's
image must still come back, and reach the asset queue. The share image's path is one the gallery does not use, so a test can
tell which rung produced the result. Not routed by `server.py`: only the
chain and writer tests read it, straight from disk.

**`vantage-abrasives/product-image-stub-redesigned.html` is the same stub
over a redesign**: the JSON-LD block unchanged, every class the template
was approved against renamed. Before ADR-0037 the stub's image made this
page "not empty", so a redesign on a domain with such an SEO plugin never
reached the inbox and never tripped `broken`. It must be an empty
extraction now, count toward the threshold when the page has worked
before, and still enqueue the share image. Read from disk, like the stub.

**`mertens/product-dialog.html` opens its dialogs before it writes the
product**, on purpose. With the product written first, a sidecar that hung on
`alert()` would still return the content and the acceptance test would pass
against a broken guard.

**`orbis-components/product-stripped.html` is the same page twice on
purpose.** Rung 1 must win on the first and rung 2 on the second, and the only
difference between them is the JSON-LD block — so a test that passes on one
and fails on the other has found a chain-ordering bug and nothing else.

**`northfield/product-redesigned.html` is the most valuable file here.** It is
the only way to test the failure that produces no error: a 200 response whose
selectors resolve to nothing. With nothing required (ADR-0027) it is
`empty_extraction` that must fire on it, and because the page _has_ a prior
observation in the test that uses it, it must count toward `broken`
(ADR-0030).

**`mertens/product-missing.html` is its mirror image** and the reason
ADR-0030 exists. Also a 200 with nothing resolving — but no prior
observation, so it must be reported and must _not_ count. A test that treats
these two the same has not tested either.

Served by `backend/tests/fixtures/server.py` over loopback. Nothing in the
suite reaches the public internet (AGENTS.md rule 14).

**Two suites consume this, and they reach it differently.** The Python suite
imports `FixtureSite` and gets an ephemeral port. The render sidecar's suite
(BUILD_PLAN `1.5`) cannot: `render` shares no network with the api (ADR-0038), so the api
container is unreachable by design. It mounts this directory at
`/fixtures` read-only and runs **this same server** on its own loopback with
`FIXTURE_HOST=127.0.0.1` — binding `0.0.0.0` there would put a resolvable
host on the egress network, which is exactly what that ADR denies. The
sidecar suite does not own a second copy of the route table: `ROUTES` is the
contract, and a reimplementation is the drift the JSON-LD twins exist to
prevent.

## Halden Tools — the discovery catalogue (`/shop/`)

BUILD_PLAN `2.1`. Every phase-2 task and the phase-2 exit test against one
invented host, `halden.test`, rendered by `catalogue.py` from two
hand-written templates (`pages/halden/{listing,product}.html`). Every page is
a pure function of path, query and `Host`.

| Shape                     | Where                                                                                                                                                             | For          |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| exact product sets        | `PRODUCTS` (64, root only); `products_under(path)`; `EXIT_PRODUCTS` (33, from `EXIT_SEED`)                                                                        | phase-2 exit |
| the exit's rules          | `EXIT_SEED = /shop/cutting/`, `EXIT_DISCOVERY`: scoped rules, facets in reach, spec 004's deny                                                                    | phase-2 exit |
| off-host product cards    | discs page 1: `elsewhere.test`, `cdn.halden.test`, look-alikes `xhalden.test`, `halden.test.elsewhere.test`                                                       | 2.3, exit    |
| pagination                | leaves, 10 per page, `?page=N`, `a[rel=next]`; discs spans 3 pages                                                                                                | 2.3          |
| subcategory nest          | `/shop/grinding/belts/{narrow,wide}/`                                                                                                                             | 2.3          |
| scoped tiles vs mega-menu | `section.subcategories` (children only) vs `nav.mega` (whole tree, on every page)                                                                                 | 2.6          |
| hidden tiles (§3a case A) | `/shop/finishing/`: tiles inside `display:none`                                                                                                                   | 2.6          |
| facet explosion           | `form.facets a`: each link adds one value; every subset is reachable, far past 20,000                                                                             | 2.3, 2.5     |
| canonical pair            | `/shop/cutting/blades/p/<sku>` names `/shop/p/<sku>`; `/shop/cutting/` features `/shop/p/HT-SB-001`, so one crawl meets both; polishes name an off-host canonical | 2.2          |
| canonicalisation material | `section.promo` on `/shop/`: tracking params, fragment, unsorted query, `./..`, `//`, case                                                                        | 2.2          |
| rejects                   | `footer.site-footer` on every listing page: off-host, subdomain, `mailto:`, `tel:`, `javascript:`, > 2,000 chars                                                  | 2.3, 2.5     |
| depth chain               | `/shop/deep/1/` … `/8/`, one tile each, off `/shop/cutting/`'s tiles: depth N from the exit seed                                                                  | 2.3          |
| calendar trap             | `/shop/news/<yyyy>/<mm>/` links the next month for ever                                                                                                           | 2.5          |
| relative-link trap        | `/shop/loop/x/page` links `loop/x/page` relative to itself for ever; the file-name segment keeps the pair under slash-stripping                                   | 2.5          |

A path with or without its trailing slash is the same page, because `2.2`
strips trailing slashes and the canonical form must be fetchable. Faceted
pages list the same products as the unfiltered page: a filter that changes
nothing is the real-world shape, and it is what makes a facet trap read as a
working crawl.

**Depths.** From the exit seed `/shop/cutting/` the deepest product is at
depth 4 (seed → discs → page 2 → page 3 → product), one level inside
`max_depth = 5`, and `/shop/deep/6/` is the first URL the cap must refuse.
From the root, the last five discs sit at exactly depth 5, which is why the
exit seeds a category.
