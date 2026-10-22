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
