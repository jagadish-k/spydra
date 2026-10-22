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

## Open questions — for the human

Carried from 2.2.

New:

1. **Subdomains are never followed** (same-host rule). Spec 004 §1's
   "subdomains configurable per domain" needs a column and the public suffix
   list; neither is built.
