# Fixtures — the local site the crawler is proven against

BUILD_PLAN `1.4`. **Hand-written, never captured** (AGENTS.md rule 2,
TESTING.md §4): a fixture has to hold still for years, and a copy of a real
page goes stale, carries someone else's content, and tempts a test into
re-fetching the original.

One file per **shape** the extraction chain must handle. The host names are
invented — nothing here is a copy of a real page and a reader should not go
looking for the original.

| Page                                     | Shape it exists to exercise                      |
| ---------------------------------------- | ------------------------------------------------ |
| `vantage-abrasives/product.html`         | well-formed, selector path (spec 003 §2)         |
| `vantage-abrasives/listing.html`         | product links + next page (spec 004 §1)          |
| `orbis-components/product-jsonld.html`   | `schema.org/Product`, structured rung 1          |
| `orbis-components/product-stripped.html` | the same page, JSON-LD removed → falls to rung 2 |
| `northfield/product-redesigned.html`     | same URL, selectors no longer match → redesign   |
| `mertens/product-rendered.html`          | content only after JavaScript (spec 012)         |
| `mertens/product-missing.html`           | soft 404: HTTP 200, no product (ADR-0030)        |
| `robots/*.txt`                           | permissive · `Crawl-delay` · disallow-all        |

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
