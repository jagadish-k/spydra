# Fixtures — the local site the crawler is proven against

BUILD_PLAN `1.4`. **Hand-written, never captured** (AGENTS.md rule 2,
TESTING.md §4): a fixture has to hold still for years, and a copy of a real
page goes stale, carries someone else's content, and tempts a test into
re-fetching the original.

One file per **shape** the extraction chain must handle. The host names are
invented — nothing here is a copy of a real page and a reader should not go
looking for the original.

| Page                                        | Shape it exists to exercise                      |
| ------------------------------------------- | ------------------------------------------------ |
| `vantage-abrasives/product.html`            | well-formed, selector path (spec 003 §2)         |
| `vantage-abrasives/listing.html`            | product links + next page (spec 004 §1)          |
| `orbis-components/product-jsonld.html`      | `schema.org/Product`, structured rung 1          |
| `orbis-components/product-stripped.html`    | the same page, JSON-LD removed → falls to rung 2 |
| `northfield/product-redesigned.html`        | same URL, selectors no longer match → redesign   |
| `mertens/product-rendered.html`             | content only after JavaScript (spec 012)         |
| `mertens/product-missing.html`              | soft 404: HTTP 200, no product (ADR-0030)        |
| `mertens/product-dialog.html`               | opens `alert()` before writing (spec 012 §3)     |
| `vantage-abrasives/product-images.html`     | 24 delayed images, for `block_resources`         |
| `vantage-abrasives/product-image-stub.html` | image-only JSON-LD stub over `product.html` (B3) |
| `robots/*.txt`                              | permissive · `Crawl-delay` · disallow-all        |

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
Product and extracts one asset URL: not empty (ADR-0027), but nothing the
content hash can compare (spec 003 §4). With the approved template the
selector rung must still win; without one the stub's image must still come
back. The share image's path is one the gallery does not use, so a test can
tell which rung produced the result. Not routed by `server.py`: only the
chain and writer tests read it, straight from disk.

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
(BUILD_PLAN `1.5`) cannot: `render` is alone on `egress`, so the api
container is unreachable by design (ADR-0023). It mounts this directory at
`/fixtures` read-only and runs **this same server** on its own loopback with
`FIXTURE_HOST=127.0.0.1` — binding `0.0.0.0` there would put a resolvable
host on the egress network, which is exactly what that ADR denies. The
sidecar suite does not own a second copy of the route table: `ROUTES` is the
contract, and a reimplementation is the drift the JSON-LD twins exist to
prevent.
