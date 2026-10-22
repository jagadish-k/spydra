# feat/2.2-canonicalisation

**Task:** BUILD_PLAN 2.2 · **Spec:** 004 §2, 001 §1 (`url_hash`) ·
**ADRs:** 0008 (ports: `domain/` is pure), 0028

Stacked on `feat/2.1-fixture-shapes` (#23).

## Contract

**One pure function decides a URL's identity, and every path that writes a
URL goes through it.**

- `spydra/domain/urls.py` (new, no I/O):
  - `canonical_url(url) -> str`: spec 004 §2 steps 1–6, in order:
    1. lowercase scheme and host; strip the default port (80/http,
       443/https);
    2. remove `.`/`..` segments (RFC 3986 §5.2.4); collapse duplicate
       slashes;
    3. strip the fragment;
    4. drop tracking parameters: any `utm_*`, `gclid`, `fbclid`, `msclkid`,
       `ref`, `_ga`, `mc_cid`, `mc_eid`;
    5. sort the remaining parameters, by key then value, **without
       re-encoding them** (a site's `%2F` stays `%2F`; blank values kept);
    6. strip a trailing slash except at the root.
  - `url_hash(url) -> bytes`: `sha256(canonical_url(url))`. Moves here from
    `adapters/postgres/frontier.py`, which re-exports it, so hashing a
    non-canonical URL is no longer possible.
- **Step 7, `rel="canonical"`:** `canonical_link(html, page_url) -> str |
None` (new, `spydra/discovery/canonical.py`, selectolax): the first
  `<link rel="canonical" href>` resolved against the page URL, canonicalised,
  and returned **only when it is on the same host** (scheme may differ? no:
  same scheme and host after step 1). Off-host, missing, empty or
  unparseable → `None`.
- **Where it applies:**
  - every write of `crawl_queue.url`/`url_hash` (the loader's seeds,
    `Frontier.enqueue`) stores the canonical URL;
  - `PageCrawler` upserts the `pages` row under `canonical_link(...)` when
    present, otherwise under the (already canonical) queue URL. That is what
    collapses two URLs into one page row (spec 004 §5).
- **No per-domain tracking list.** Spec 004 §2 step 4 says "plus a
  per-domain list"; there is no column for it and nothing in phase 2 needs
  one. Raised, not built.

## Files this slice owns

- backend/spydra/domain/urls.py (new)
- backend/spydra/discovery/{**init**,canonical}.py (new)
- backend/spydra/adapters/postgres/{frontier,pages,configuration}.py
- backend/spydra/scheduler/crawl.py (page upsert under the canonical)
- docs/specs/004-discovery.md §2 (only if the build forces a wording fix)
- backend/tests/** (test-writer)
- docs/BUILD_PLAN.md (tick)

## Acceptance (BUILD_PLAN 2.2 + spec 004 §5)

- [ ] `?b=2&a=1` and `?a=1&b=2` hash identically.
- [ ] `utm_source` is stripped while `?page=2` survives.
- [ ] Every `section.promo` spelling on Halden's `/shop/` canonicalises to
      `http://halden.test/shop/cutting/discs` (the `?page=2` one to
      `…/discs?page=2`), through the served HTML.
- [ ] A `rel="canonical"` to elsewhere on the same host collapses two URLs
      into one `pages` row: crawling Halden's `/shop/cutting/blades/p/<sku>`
      and `/shop/p/<sku>` in one run yields one page row; the off-host
      canonical (polishes) is ignored.
- [ ] The loader stores canonical seed URLs; `Frontier.enqueue` stores
      canonical URLs and dedupes two spellings of one URL to one row.
- [ ] `canonical_url` is idempotent (property over the fixture's spellings).
- [ ] `make check` green; mutation: each step broken alone turns a test red.

## Handoff log

- planner (main session): contract above.
- backend (main session):
  - `domain/urls.py`: `canonical_url` (steps 1–6) and `url_hash` over it.
    The query is split and sorted as written (keys decoded only to spot
    tracking params, and for the sort key), never re-encoded. Credentials in
    a link are dropped with the netloc rebuild. `frontier.url_hash` is gone;
    the adapter re-exports the domain one, so old imports keep working.
  - Every URL write stores `canonical_url(url)`: `Frontier.enqueue`, the
    loader's seeds, `PostgresPages.upsert`.
  - `discovery/canonical.py`: `canonical_link(html, page_url)`; same scheme
    and host only. `PageCrawler._observe` upserts the page under it on a
    200, else under the queue URL; the writer's `CrawledPage.url` follows,
    so an inbox row names the canonical too.
  - **Fixture change:** `server.py` serves `ROUTES` with or without the
    trailing slash. The vantage listing is routed as
    `/catalog/abrasives/discs/`, whose canonical form would otherwise 404.
  - Smoke: every Halden promo spelling → `http://halden.test/shop/cutting/
discs` (the unsorted pair → `?colour=red&per_page=25`, `?page=2` kept);
    blades context page → `/shop/p/HT-SB-001`; polishes' off-host canonical
    → `None`. Full suite unchanged: 679 passed, 2 skipped.
  - **Consequence to know:** a dev database crawled before this holds
    `pages`/`crawl_queue` rows hashed from the raw URL. A non-canonical one
    (trailing slash, tracking params) gets a new page row on its next crawl;
    its history stays on the old row. No data migration: it would need this
    function inside a migration, which the repo forbids (old migrations
    freeze their SQL). Raised.
- test (spydra-test): 229 tests in 4 new files, written from Contract and
  Acceptance. **228 pass, 1 red on purpose (a defect, below).**
  - `tests/domain/test_canonical_url.py` (182, mostly parametrised). Each
    of steps 1–6 is pinned on its own, in both directions: what a step must
    remove and what it must leave alone. Covers look-alike names (`reference`,
    `utm`, `xutm_source`, `gclid_id`), dots inside a segment, and `//` inside
    a query value. Tracking: every name plus the `utm_*` prefix, blank
    values, and escaped keys (`utm%5Fsource`, `%67clid`, `%5Fga`). Sort: by
    key then value; repeats kept; `%2F`, `+`, `%20` and `%C3%A9` kept as
    written; blank values kept. Root keeps its slash. Credentials dropped.
    Idempotence and `url_hash(x) == sha256(canonical_url(x))` are checked
    over every spelling. Also the two spec 004 §5 hash criteria, and seven
    pairs that must hash _differently_.
  - `tests/discovery/test_canonical_link.py` (35). Unit cases cover same
    host, root- and path-relative hrefs, the canonical itself canonicalised,
    off-host (other host, subdomain, both look-alikes, scheme-relative),
    another scheme, missing, empty or blank href, no href, several and mixed-case
    `rel` tokens, `noncanonical`/`canonicalish`, and first-wins (including
    an off-host first). Halden cases go through `FixtureSite`'s HTML: every
    `section.promo` spelling → `http://halden.test/shop/cutting/discs`,
    except the unsorted pair (→ `?colour=red&per_page=25`) and `?page=2`.
    Blades → `/shop/p/HT-SB-001`; polish → `None`.
  - `tests/adapters/postgres/test_canonical_writes.py` (6, real Postgres).
    `Frontier.enqueue`: two spellings → one row, canonical `url` and
    `url_hash`; `?page=2` stays apart; credentials are never stored. The
    loader (`load()`) stores canonical seeds and dedupes them.
    `PostgresPages.upsert`: two spellings → one row.
  - `tests/scheduler/test_canonical_pages.py` (6, real Postgres, real
    `PageCrawler` + `HttpxFetcher` against `FixtureSite`). Blades-context
    and canonical URLs crawled in one run → both rows `done`, ONE `pages`
    row under `/shop/p/HT-SB-001` with 2 observations, in either order.
    The context URL alone files under the canonical. The polish's off-host
    canonical leaves it under its own URL. A listing with no canonical files
    under the canonical queue URL.
  - **Mutation: 25 chosen, 24 red.** One mutant per step of
    `canonical_url`, plus finer ones (prefix, escaped key, key-only sort,
    re-encoding, blank drop, root slash). Also `url_hash` over the raw URL;
    five `canonical_link` mutants (host check removed, scheme ignored,
    off-host skipped to the next link, empty href, rel substring); and each
    write path's `canonical_url(...)`: frontier, loader, pages, and
    `PageCrawler`'s `canonical_link`. The survivor is "drop
    `_SLASHES.sub`". It is **equivalent**: `posixpath.normpath` already
    collapses `//`, and the leading `//` is handled by the `lstrip`, so no
    input tells them apart. `git diff -- backend/spydra` is empty afterwards.
  - Full backend suite: **1 failed, 907 passed, 2 skipped**. The failure is
    the defect below. `make lint-api` clean.
  - **Defect (left red):**
    `test_a_bracketed_ipv6_host_keeps_its_brackets`.
    `canonical_url("http://[::1]:8080/shop")` returns
    `http://::1:8080/shop`. The netloc is rebuilt from `parts.hostname`,
    which drops the brackets, so the result is not a parseable URL.
    Canonicalising it again raises in `urlsplit(...).port`. Low exposure on
    supplier sites, but it is a step-1 bug. The fix is to re-bracket when the
    host contains `:`.
  - **Finding (not a 2.2 code defect, needs an owner):** any page with
    `<link rel="canonical">` makes extruct's pyRdfa call the deprecated
    `datetime.utcnow()`. Verified in the api image:
    `extruct.extract(<link rel=canonical>, syntaxes=['rdfa'])` under
    `-W error::DeprecationWarning`. Under the suite's
    `filterwarnings = ["error"]`, that raises inside the structured rung,
    so `PageCrawler` cannot crawl any Halden product page in a test. Production only
    gets an ignored DeprecationWarning. `test_canonical_pages.py` carries a
    module-scoped `filterwarnings` ignore for that one message from
    `pyRdfa`, with the reason and a removal condition. The phase-2 exit and
    2.3+ will hit the same thing, so this probably belongs in
    `pyproject.toml` (not a test-writer file). It needs a backend/ops decision.
  - Not tested: the per-domain tracking list (not built, open question 1).
    The `/a//../b` ordering inside step 2 is also untested, because spec
    004 does not say whether `..` or `//` goes first.

- backend (after test):
  - **Fixed the defect the tests found:** an IPv6 host lost its brackets
    (`hostname` drops them), so `http://[::1]:8080/x` canonicalised to an
    invalid URL. Brackets restored; the red test is green.
  - **The one survivor was equivalent, so its code is gone:** the `//`
    regex ran before `posixpath.normpath`, which already collapses `//`.
  - **pyRdfa's `utcnow()` DeprecationWarning** moved from a per-file mark
    to `pyproject.toml`'s `filterwarnings`, scoped to that one message and
    module: every page with a canonical (2.3 onwards, the exit) hits it.
  - Suite: 908 passed, 2 skipped; lint clean.

## Open questions — for the human

Carried from 2.1 and 2.0.

New:

1. **Per-domain tracking parameters** (spec 004 §2 step 4) need a
   `domains` column and an operator surface (phase 3). Not built.
2. **Pre-2.2 rows are not re-keyed** (see the backend entry). `make reset`
   on a dev database is the clean answer; nothing is in production.
3. **Scheme is part of identity.** `http://h/x` and `https://h/x` are two
   URLs. A site that serves both would be crawled twice; a redirect usually
   settles it. Left as spec 004 has it.
