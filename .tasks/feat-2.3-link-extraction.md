# feat/2.3-link-extraction

**Task:** BUILD_PLAN 2.3 · **Spec:** 004 §1, §5; 001 §1 (`domains.max_depth`,
`deny_patterns`; `templates.discovery`) · **ADRs:** 0002, 0008

Stacked on `feat/2.2-canonicalisation` (#24).

## Contract

**One pure function says what a page leads to, with the reason for every
link it drops; the crawler enqueues what it accepts.** The same function is
2.10's dry-run, so it returns grouped results, not just a list.

- `spydra/discovery/links.py` (new, pure, selectolax):
  `discover(html, page_url, rules, *, host, depth, max_depth,
domain_deny) -> Discovery`.
  - For each rule that is set (`product_links`, `next_page`,
    `subcategory_links`): every `href` its selector matches, resolved against
    `page_url` (the URL the body came from).
  - Kept only if all hold (spec 004 §1):
    1. **same host** as the domain (see "Decided" below);
    2. scheme `http`/`https`;
    3. matches an `allow_pattern`, if any are set;
    4. matches no `deny_pattern` (the template's and the domain's);
    5. **the page's depth is below `max_depth`**, so its links get
       `depth + 1 ≤ max_depth`.
  - Patterns are searched against **path + query** of the canonical URL.
  - Result: `accepted` grouped by rule, each a list of `(url, depth)` with
    duplicates within the page removed by `url_hash`; `rejected` grouped by
    reason (`off_host`, `scheme`, `not_allowed`, `deny_pattern` with the
    pattern, `depth`), with counts and samples. A link a rule matched and a
    reject reason are recorded once, under the first rule that matched it.
  - Unparseable hrefs are rejected (`unparseable`), never raised.
- **`PageCrawler`:** on a 200 whose page matched a template with discovery
  rules, call `discover` and `Frontier.enqueue(run, domain, accepted)`.
  Seeds are depth 0 (the queue already stores depth). Discovery runs on the
  final observation's page (after any AUTO second chance), so a rendered
  page's links count.
- **Logging:** one `debug` line per page with accepted/rejected counts. No
  `info` per page (spec 009 §1).

### Decided (planner)

- **Depth, spec 004 §1 vs §5.** They agree once read as "a page at depth d
  expands only while d < `max_depth`": its links are depth d+1 ≤ max_depth,
  so at `max_depth = 5` depth-5 pages are enqueued and depth-6 links are not
  (§5). Written into spec 004 §1. Closes 2.1 open question 2.
- **`max_depth` and `deny_patterns` live on the domain** (spec 001 §1
  already says so: "the Domain detail screen edits them"); the template's
  `discovery.deny_patterns` add to them. Closes 2.1 open question 1. Spec 004
  §1's JSON example is edited to drop `max_depth` from the template.
- **"Same registrable domain" is enforced as "same host".** A registrable
  domain needs the public suffix list, a new dependency (ADR, wheel check)
  for no phase-2 need: politeness and templates are per host (one `domains`
  row per host), so a subdomain is another domain row anyway. The stricter
  rule satisfies "never leaves the registrable domain". The "subdomains
  configurable" switch is not built. Raised.

## Files this slice owns

- backend/spydra/observations/writer.py,
  backend/spydra/adapters/postgres/observations.py (ADR-0039)
- docs/adr/0039-*.md, docs/adr/README.md, docs/adr/0027 (status line)
- compose.yaml (`halden.fixtures` alias)

- backend/spydra/discovery/links.py (new)
- backend/spydra/scheduler/crawl.py (call discover + enqueue)
- backend/spydra/adapters/postgres/templates.py (only if the codec needs it)
- docs/specs/004-discovery.md §1 (depth wording, JSON example)
- backend/tests/** (test-writer)
- docs/BUILD_PLAN.md (tick)

## Acceptance (BUILD_PLAN 2.3, spec 004 §5)

- [ ] Depth-6 links are not enqueued at `max_depth = 5`; depth-5 are.
      Through the worker from Halden's `EXIT_SEED`: `/shop/deep/5/` queued,
      `/shop/deep/6/` never.
- [ ] An off-host link is dropped: Halden's four `PARTNER_CARDS` never reach
      `crawl_queue`, look-alikes included.
- [ ] A faceted listing is capped by `deny_patterns`: with Halden's
      `EXIT_DISCOVERY`, no faceted URL is enqueued, and the rejected count is
      reported.
- [ ] `discover` on a fixture page returns per-rule groups and per-reason
      rejects with counts and samples; writes nothing (pure).
- [ ] A crawl from `EXIT_SEED` with `EXIT_DISCOVERY` enqueues and crawls
      exactly `EXIT_PRODUCTS`' product pages (no facet explosion, no
      off-host), politely, to a completed run.
- [ ] `mailto:`/`tel:`/`javascript:` are rejected as `scheme`.
- [ ] A listing-template page with no fields opens no inbox row and is not
      in the health counts (ADR-0039); a product page still is.
- [ ] A page fetched as `/x/` matches a template written for `/x`.
- [ ] `make check` green; mutation on each filter rule.

## Handoff log

- planner (main session): contract and decisions above.
- backend (main session):
  - `discovery/links.py`: `discover(...) -> Discovery` (accepted per rule,
    `(fetchable url, depth)`; rejected per reason, deny keyed per pattern;
    counts and up to 5 samples). Scheme is checked before canonicalising,
    so `mailto:` counts as `scheme`, not `unparseable`. Within-page dedupe
    by canonical hash; a link is attributed to the first rule in
    product → next → subcategory order.
  - `PageCrawler._discover`: after the observation, before the row closes
    (so the run cannot look drained in between), never on a halted domain
    (its rows would never be claimed and the run would never finish). One
    `debug` line per page with counts.
  - **Defect found by smoke, fixed:** templates were matched against the
    queue URL's path as written. Since 2.2 the queue fetches the discovered
    spelling, so `/shop/cutting/` failed a pattern written for
    `/shop/cutting`. `_path` now matches on the canonical URL.
  - **Decision, ADR-0039:** a page matched by a `listing` template is
    outside the extraction verdict (no `empty_extraction` inbox reason,
    not in ADR-0030's counts). Without it every listing page was an empty
    extraction, and a category crawl's first run would move the domain to
    `awaiting_approval`. Spec 001 already defines `page_kind`; nothing in
    the specs said how the verdict treats listings.
  - `compose.yaml`: `halden.fixtures` alias on the profile-only `fixtures`
    service, for the phase-2 exit.
  - Spec 004 §1: depth wording, same-host rule, `max_depth` on the domain.
  - **Smoke** (dev DB, real worker, `fixtures` service, a scratch YAML with
    a listing template carrying Halden's `EXIT_DISCOVERY` and a product
    template, seed `/shop/cutting/`): run `completed`; 44 queue rows, 34 of
    them product URLs and **33 distinct product pages** (the canonical pair
    collapsed); 0 facet URLs, 0 off-host; `/shop/deep/5/` queued,
    `/shop/deep/6/` not, max depth 5; domain stays `active`. Full suite
    986 passed before the `_path` fix.
- test (spydra-test): written from Contract, Decided and Acceptance; the
  backend entry read for orientation only. 37 tests in three files:
  - `tests/discovery/test_links.py` (26, unit, Halden pages served by
    `FixtureSite` as `halden.test`): per-rule groups; per-reason rejects
    with counts and samples; deny tallied per pattern; domain deny with and
    without the template's; `scheme` for `mailto:`/`tel:`/`javascript:`;
    all four `PARTNER_CARDS` `off_host` (look-alikes included, against the
    real host name); `not_allowed`; patterns on canonical path + query;
    depth (`/shop/deep/4/` yields `/5/` at depth 5, `/shop/deep/5/` yields
    nothing and counts `/6` as `depth`); unparseable counted, not raised
    (two broken hrefs spliced into the served root: Halden has none, and
    adding them to the catalogue footer would touch every suite); dedupe by
    canonical hash, first spelling kept (the promo's 11 spellings are 3
    links); fragment dropped; product > next > subcategory attribution;
    pure (no I/O imports, not async, no request, same answer twice).
  - `tests/adapters/postgres/test_listing_verdict.py` (6, ADR-0039): an empty
    listing opens no inbox row and is not in the counts; an empty product
    page still is; a first run of 10 empty listings and 5 good products
    leaves the domain `active`; listings that extract do not dilute a 40%
    redesign; listings do not count toward the minimum sample; a listing
    write after a `broken` verdict reports no event of its own.
  - `tests/scheduler/test_link_discovery.py` (5): the worker process from
    `EXIT_SEED` with `EXIT_DISCOVERY` (20 ms delay, one connection):
    exactly `EXIT_PRODUCTS` observed as product pages, nothing off-host and
    no facet URL ever queued or requested, `/shop/deep/5/` done at depth 5
    and `/6/` never queued or requested, run `completed`, domain `active`,
    empty inbox. Through `PageCrawler`: `/shop/cutting/` matches
    `^/shop/cutting$`; the domain's `deny_patterns` reach the crawl; a page
    whose observation halts its domain enqueues nothing (plus its control).
  - **Defect 1, test left red:**
    `test_a_rejected_link_two_rules_match_is_counted_once`. The contract
    says a link "and a reject reason are recorded once, under the first
    rule that matched it". `discover` tallies `scheme` (and `unparseable`)
    before the within-page dedupe, so the root footer's `mailto:` under two
    rules counts `scheme` 6, not 3, with duplicate samples. `off_host`,
    tallied after dedupe, is right (2).
  - **Defect 2, test left red, pre-existing since 1.13 (`600d912`):**
    `test_a_page_whose_observation_halts_its_domain_enqueues_nothing[halted]`.
    `PageCrawler._observe` calls `log.error("domain_halted",
event=outcome.event, ...)`; `event` is structlog's positional, so every
    mid-run halt raises `TypeError` after `abandon_domain` and before the
    row is closed. In the worker, `abort` then retries the row. No earlier
    test drove a real halt through `PageCrawler`. It also masks the 2.3
    halted-domain guard, so that guard's mutant was run on top of the
    one-line log fix (`event=` → another key), and the baseline with only
    that fix is fully green.
  - **Mutation: 21 chosen, 21 red.** `discover`: each filter rule
    (off-host, scheme, allow, deny), `>=` → `>`, `depth + 1` → `depth`, the
    deny merge both ways, `except ValueError`, the dedupe, rule order,
    canonical instead of fetchable. Crawler: `max_depth` not the domain's,
    domain deny dropped, nothing enqueued, the halted guard, `_path`
    without canonicalisation. ADR-0039: `_extracted` in `_reason` and in the
    health guard, and the `page_kind` filter in `_RUN_PAGES` and in
    `_PAST_MINIMUM` separately. `git diff -- backend/spydra` empty after.
  - Full backend suite: 1021 passed, 2 skipped, 2 failed (the two defects
    above). `make lint-api` clean.
  - Not tested: the one `debug` line per page (spec 009 §1). The crawl's
    "politely" is the real gate at one connection and a 20 ms delay, not
    an assertion on request timing; `test_politeness_observed.py` owns that.

## Open questions — for the human

Carried from 2.2.

New:

1. **Subdomains are never followed** (same-host rule). Spec 004 §1's
   "subdomains configurable per domain" needs a column and the public suffix
   list; neither is built.
