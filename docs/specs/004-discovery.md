# 004 — Discovery, canonicalisation and traps

**Phase 2** · depends on 002, 003

Seeds are category and listing pages. The crawler follows pagination,
subcategory links and product links to depth 5. Discovery rules are **part of
the approved template**, not heuristics — which is what makes this
deterministic and reviewable.

---

## 1. Rules

From `templates.discovery`:

```json
{
  "next_page": "a[rel='next']",
  "product_links": "a.product-card__link",
  "subcategory_links": "nav.cat-tree a",
  "allow_patterns": ["^/catalog/", "^/products/"],
  "deny_patterns": ["[?&](colour|grit|sort|view|per_page)=", "/compare"]
}
```

`max_depth` (default 5) and a further `deny_patterns` list live on the
**domain** (spec 001 §1); a link must pass both lists. Patterns are searched
against the canonical URL's path and query (§2). Rules are applied only on a
page matched by a template; hrefs resolve against the document's
`<base href>` if it has one, else the URL the body was served from, by `spydra.discovery.links.discover`, which the dry-run (§4) shares.

Each extracted link is kept only if **all** hold:

1. Same host as the domain. Stricter than "same registrable domain": a
   subdomain is its own `domains` row (politeness and templates are per
   host), and following subdomains needs the public suffix list. Not built.
2. Scheme is http or https.
3. Matches at least one `allow_pattern` if any are set.
4. Matches no `deny_pattern`.
5. The page being expanded is at a depth below `max_depth`, so its links are
   at most `max_depth` deep: at `max_depth = 5`, depth-5 pages are enqueued
   and their depth-6 links are not (§5).
6. Not already in `crawl_queue` for this run (`UNIQUE (run_id, url_hash)`).
7. Its canonical URL is at most 2,000 characters long — the canonical
   spelling, because it is the one hashed and enqueued (§2).
8. Its canonical path does not match a calendar pattern —
   `/20\d\d/\d\d(/|$)`, matched at the month's end because the canonical
   path carries no trailing slash (§2) — unless an `allow_pattern`
   matched. The operator's explicit yes outranks the calendar defence (§3).
9. Its canonical path contains no block of one or more segments repeated
   three full times in immediate succession (§3).

The three structural checks (7–9) run in `discover` between rule 3 and
rule 4: a link an `allow_pattern` matched walks past the calendar check,
while length and repetition are facts about the URL's own shape and hold
regardless.

## 2. Canonicalisation

Applied before hashing, in this order. Getting it wrong means either
duplicate crawls or missed pages.

1. Lowercase scheme and host; strip the default port.
2. Resolve `.` and `..`; collapse duplicate slashes.
3. Strip the fragment.
4. Remove tracking parameters: `utm_*`, `gclid`, `fbclid`, `msclkid`,
   `ref`, `_ga`, `mc_cid`, `mc_eid`, plus a per-domain list.
5. **Sort the remaining query parameters.** `?a=1&b=2` and `?b=2&a=1` are the
   same page.
6. Strip a trailing slash except at the root.
7. Honour `<link rel="canonical">` when it points to the same host — this is
   the site telling you its own answer.

`url_hash = sha256(canonical_url)`, which is what `UNIQUE (domain_id,
url_hash)` and `UNIQUE (run_id, url_hash)` use.

## 3. Traps

Faceted navigation is the one that kills crawls. `?colour=red&size=10&sort=asc`
generates a combinatorial URL space that is effectively infinite, and every
URL looks legitimate.

Defences, in order of effectiveness:

1. **`deny_patterns` on the template**, reviewed by the operator. The
   dry-run tool (§4) exists so this is caught before a run.
2. **Per-run URL cap per domain**, default 20,000. On breach the run is
   failed with the cap named as the reason and the domain's pending rows in
   that run are abandoned; the domain itself stays `active` and the next
   run starts clean (ADR-0040). The dry-run report names the pattern that
   exploded, grouped by the discovery rule that matched it.
3. **Depth cap**, default 5.
4. **Repeating-path detection** — one contiguous block of one or more path
   segments repeated three **full** times in immediate succession
   (`/a/b/a/b/a/b/` trips on `a,b`; `/x/deeper/deeper/deeper/` on `deeper`).
   A 2.5-cycle path (`/a/b/a/b/a/`) does not trip; the third full
   repetition does.

Also reject: `mailto:`, `tel:`, `javascript:`, canonical URLs over 2,000
characters, and anything matching a calendar pattern (`/20\d\d/\d\d(/|$)`,
at the month's end — the canonical path has no trailing slash) — unless an
`allow_pattern` matched it: the calendar check runs after the allow check,
so the operator's reviewed pattern is the explicit permission (a broad
allow implicitly permits calendars; the dry-run is where that becomes
visible).

## 3a. Navigation the crawler cannot see

Cascading menus, mega-menus and hover-revealed category trees. Three cases
that look identical in a browser and are completely different to a crawler.
**Diagnose before building anything** — the cheap case is the common one.

| Case                            | What is in the fetched HTML                                     | Cost     |
| ------------------------------- | --------------------------------------------------------------- | -------- |
| **A — hidden by CSS**           | the `<a href>` is there, `display:none` until hover             | free     |
| **B — injected on interaction** | the data is there (inline JSON, a JS bundle), the links are not | small    |
| **C — fetched on interaction**  | nothing; hovering fires an XHR                                  | moderate |

### Case A is free, and the risk runs the other way

`selectolax` parses markup; it does not compute styles, so a link hidden by
`display:none` is an ordinary match. Most bespoke supplier sites are
server-rendered and land here. **Nothing needs building.**

The real hazard is the opposite one: a mega-menu often lists _the entire
category tree on every page_. A `subcategory_links` rule scoped to `nav a`
therefore discovers the whole site from depth 0, defeats the depth cap, and
looks like a working rule right up until the URL cap fails the run. Scope
the selector to the menu's own container and let `allow_patterns` and the
dry-run (§4) confirm the count before approval.

### Prefer the path already in the crawl

Before reaching for B or C: **a cascading menu is usually a shortcut to pages
that are reachable anyway.** Category pages carry subcategory tiles and
pagination; the menu is a faster route to the same URLs, not a different set.
If depth 5 from the seed reaches them through listing pages, discovering them
from the menu adds fragility and no coverage.

Check this with the dry-run before building anything: run it on one
category page with `subcategory_links` set and again with it unset, and
compare `projected_urls_at_max_depth`. **Count equality can never prove set
equality** — the "menu is a shortcut, not new coverage" case has identical
reachable sets and different fan-outs, so whether two projections spell the
same URL set is undecidable from one page, and always was. What the
comparison decides safely: **a rule whose removal leaves the projection
unchanged enqueues nothing the other rules don't — delete it** (first-match
attribution makes this exact: links another rule already matched
re-attribute, and the fan-out `t` is unchanged). A rule whose removal
lowers the projection adds volume, and whether that volume is coverage or
shortcut is the operator's call, informed by the mega-menu finding and the
samples.

### Case B — reveal, then read

When the links genuinely only exist after interaction, the sidecar gets a
`reveal` step (spec 014 §2a): a bounded list of selectors to hover or click
before capture. Same mechanism as `expand`, extended from `<details>` and
`aria-expanded` to arbitrary elements with an explicit action.

```json
"reveal": [
  {"selector": "nav.mega > li", "action": "hover", "all": true, "wait_ms": 150}
]
```

Bounded at 20 elements and 3 s total, and **the reveal set is stored on the
template** so the run reproduces exactly what the operator approved. An
unbounded "click everything" pass is a different program with different
failure modes; do not write one.

Often there is a cheaper route in this case: the menu data frequently ships
as inline JSON (`<script type="application/json">`, a `__NEXT_DATA__` blob, a
`window.__NAV__` assignment). A `discovery.json_source` rule — a selector plus
a JSONPath to an array of hrefs — is more durable than any amount of hovering,
because it does not depend on the menu's markup at all.

### Case C — record the request, do not replay the hover

When hovering fires `GET /api/nav/children?id=42`, the sidecar already has
the answer: it holds the network log for the render. So capture it.

`/inspect` returns `network[]` — requests issued during reveal, with method,
URL, status and content type. In the playground, hovering a menu surfaces
_"this produced 3 requests; one returned JSON containing 24 URLs"_, and the
operator can promote that endpoint to a discovery rule.

**An endpoint is a better discovery rule than an interaction.** It survives
redesigns that rewrite the menu markup, costs one request instead of a full
render, and is reviewable as a URL rather than as a script. The cost is that
it is an undocumented internal API that can change without notice — so it is
versioned on the template like any other rule, and a rule whose endpoint
starts returning non-JSON fails loudly rather than silently discovering
nothing.

**Politeness applies unchanged.** A revealed render is one page fetch against
the per-domain gate, and a promoted endpoint is a normal queued URL. Neither
gets a side channel.

## 4. Dry-run discovery

Exposed on the template review screen as a button. It crawls **one** listing
page and returns exactly what would be enqueued, grouped by the rule that
matched:

```json
{
  "matched": {
    "product_links": {
      "count": 48,
      "sample": ["https://halden.test/shop/p/HT-CD-001", "..."]
    },
    "next_page": {
      "count": 1,
      "sample": ["https://halden.test/shop/cutting/discs?page=2"]
    },
    "subcategory_links": { "count": 11, "sample": ["..."] }
  },
  "rejected": {
    "deny_pattern:[?&](colour|grit|sort)=": {
      "count": 312,
      "pattern": "[?&](colour|grit|sort)=",
      "sample": ["..."]
    },
    "off_host": { "count": 7, "sample": ["..."] }
  },
  "mega_menu": {
    "links": 11,
    "paths": 11,
    "branches": 3,
    "levels": 3,
    "roots": ["/shop/cutting", "/shop/finishing", "/shop/grinding"]
  },
  "projected_urls_at_max_depth": 1357260,
  "fetch_path": "static",
  "http_status": 200,
  "final_url": "https://halden.test/shop/cutting/discs",
  "notices": []
}
```

This is where a facet trap is caught before it generates 40,000 URLs, and it
is far cheaper than catching it mid-run.

Samples are absolute fetchable URLs — an operator must be able to open one.
The report is `spydra.discovery.dry_run.dry_run`, which makes exactly one
robots request and at most one page request, through the fetcher the caller
resolved for the domain's `render_mode`. A robots disallow or a fail-closed
robots fetch (spec 002 §5) means **zero** page requests — the crawl would
refuse the domain, and the report says so rather than silently reporting
zero links. An AUTO domain gets no rendered second chance here (ADR-0039):
a static fetch whose discovery accepts zero links is the one ambiguous case
(broken selector or JS-dependent listing), and it is reported loudly rather
than rendered around. The notice tokens: `robots_disallowed`,
`robots_unavailable`, `fetch_failed`, `non_200` (rules run against a 403
body are garbage — no discovery runs), and `zero_links_static`.

`projected_urls_at_max_depth` — `max_depth`, not a hard-coded 5; the earlier
name `projected_urls_at_depth_5` lied whenever a domain's cap differed — is
a deterministic arithmetic **estimate** of the URLs a crawl from this one
page would enqueue through `max_depth`, by the multiplicative fan-out model.
From the report's own matched counts — `p` product links, `n` next-page
links, `s` subcategory links — with `t = p + n + s` (total fan-out per
listing) and `f = n + s` (fan-out into pages that expand further), products
as leaves (a product template discovers nothing, spec 001 §1), and
`D = max_depth`:

```
projected = t · (f^D − 1) / (f − 1)    f > 1
projected = t · D                      f = 1
projected = t                          f = 0
```

It is not a count of known URLs, not a set, and it cannot see dedupe or the
site's closure: those live on pages it did not fetch. The example above
derives its 1,357,260 from its own counts (`t = 60`, `f = 12`, `D = 5`) —
any reader can recompute it, which is the point of an example. On Halden,
`nav a` on `/shop/cutting/` (`t = 11`, `f = 11`, `D = 5`) projects 177,155
— the model says "if every page yields 11 new listings, by depth 5 you
visit ~177k URLs", which is the hazard signal, not a prediction: the real
crawl dedupes a finite site down to its 11 categories. The scoped leaf's
rules (`t = 11`, `f = 1`) project 55. That gap is the whole point.

The mega-menu guard joins the report: when a `subcategory_links` rule spans
two or more branches from one page — a site-wide menu's shape, not one
container's tiles (§3a) — the report carries the finding from
`spydra.discovery.mega_menu.whole_tree`: the spanning roots, the link count,
the deepest chain, so the operator scopes the selector before approval. Its
blind spot is deliberate and named: a menu nested under a single top-level
branch is invisible to structure, and §3a's "prefer the path already in the
crawl" check — `projected_urls_at_max_depth` with the rule set and with it
unset — is the backstop.

## 5. Acceptance

- [ ] `?b=2&a=1` and `?a=1&b=2` produce the same `url_hash`.
- [ ] `utm_source` is stripped; a meaningful `?page=2` is not.
- [ ] A seed with a faceted listing is capped by `deny_patterns` and the
      dry-run reports the rejected count.
- [ ] Depth 6 links are not enqueued when `max_depth` is 5.
- [ ] A run breaching the per-domain URL cap is failed with the cap and the
      host named as its `stop_reason`, its pending rows for that domain
      abandoned and counted in `pages_abandoned`, and the domain itself
      still `active` (ADR-0040). Naming the pattern that exploded is the
      dry-run's job (§4, 2.10).
- [ ] A `rel="canonical"` pointing elsewhere on the same host collapses two
      URLs into one page row.
- [ ] Discovery never leaves the registrable domain.
- [ ] A fixture whose subcategory links are `display:none` is discovered by a
      static fetch with no reveal step.
- [ ] A `nav a` rule on a mega-menu fixture is caught by the dry-run as
      discovering the whole tree at depth 0.
- [ ] A reveal step bounded at 20 elements stops at 20 and says so.
- [ ] A template's reveal set is stored and replayed identically on the run.
- [ ] A `json_source` rule extracts hrefs from an inline JSON blob without a
      browser.
- [ ] An endpoint promoted from the network log enqueues as an ordinary URL
      against the per-domain gate.

## 6. CSV seed files

Onboarding many seeds fast, while templates still come from YAML
(`spydra.seed_csv` + `spydra.load_seeds`, BUILD_PLAN 2.9). **Scaffolding
with a deletion date**: `3.2` deletes the YAML loader and deletes these
with it. No schema, no validator framework — the minimum format below, and
nothing anyone could grow attached to.

```csv
host,seed_url,render_mode,crawl_delay_ms
vantage-abrasives.test,https://vantage-abrasives.test/catalog/abrasives
halden.fixtures:8099,http://halden.fixtures:8099/catalog,rendered,5000
```

**The header is the column contract** — exact, ordered, lowercase, and one
of `host,seed_url` / `host,seed_url,render_mode` /
`host,seed_url,render_mode,crawl_delay_ms`. A wrong or missing header
refuses the whole file: inferring it turns row 1's data into column names
and makes every later reject unnameable. Fields are stripped of surrounding
whitespace (the one hand-edited forgiveness); lines blank after stripping
are skipped silently; there is no comment syntax. Stdlib `csv` quoting,
UTF-8.

Columns and defaults, matching the YAML loader exactly: `render_mode`
defaults `static`, `crawl_delay_ms` defaults `2000`, and
**`respect_robots` is not a column** — fixed `true`, the domain default.
`seed_url` must be an absolute http/https URL; `host` is cross-checked
against its netloc (case-insensitive, port included) by the same rule as the
YAML loader's — a seed is crawled under its domain's robots.txt and
politeness, so it belongs under the domain it is on. Host validation is
syntax-only: no DNS, no `getaddrinfo`, and nothing in the parser can make a
network call.

A CSV carries **no templates, ever** (ADR-0006 is untouched — a template
cannot be expressed here). A template-less domain is crawled honestly: the
structured (JSON-LD) rung runs without a template, every 200 lands in
`unknown_pages` as `no_template`, the domain is never moved to
`broken`/`awaiting_approval` by its template-less pages, and discovery never
expands — the run crawls exactly the file's seeds and drains. Domains land
`active`; the inbox says "give these domains templates".

### Per-row rejects

CSV is row-oriented: one typo in row 40 of 200 does not cost the file, and
unlike YAML the rows share no structure — 200 independent facts, not one
coherent template set. A rejected row is reported and skipped; the rest
import. **The database transaction is still all-or-nothing** — rejects are
removed before `apply` runs, so a partial import never half-writes.

Rejects name the **file line number** (what the operator's editor shows;
header is line 1, first data row line 2):

| Token             | When                                                                                                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `empty_host`      | host blank after strip                                                                                                                                                         |
| `empty_seed`      | seed_url blank after strip                                                                                                                                                     |
| `bad_url`         | no scheme or no netloc — a path-only seed, not a guess                                                                                                                         |
| `off_scheme`      | scheme not http/https (`mailto:`, `javascript:`, …; rule §1.2)                                                                                                                 |
| `host_mismatch`   | netloc ≠ host, case-insensitive, port included                                                                                                                                 |
| `bad_render_mode` | not exactly `static`, `rendered` or `auto`                                                                                                                                     |
| `bad_delay`       | not a whole number of milliseconds ≥ 0 (the CHECK, caught early)                                                                                                               |
| `column_count`    | wrong field count for the header                                                                                                                                               |
| `conflict`        | same host, different `render_mode`/`crawl_delay_ms` than an earlier accepted row — a domain has one setting, and picking one silently is the guess this loader refuses to make |

An exact duplicate `(host, seed_url)` is **deduplicated silently**: the
enqueue is `ON CONFLICT DO NOTHING`, so the second row's outcome is
byte-identical to the first's and reporting it would report a non-failure.

File-level refusals (`refused:`, nothing written, exit 1): a bad header; a
header with no data rows; every data row rejected; every domain refused
(no run is started over nothing). A domain already `paused`, `broken` or
`archived` — a conflict with the world, not with a row's syntax — is
refused **alone**: its rows are skipped, the rest of the file imports, and
the run covers what imported. The YAML loader keeps the whole-file
refusal (a YAML file is one coherent template set; a CSV is independent
facts), which is why the refusal is `apply(skip_refused=True)` and not a
behaviour change to `spydra.load`.

**Exit codes** — the only channel `make` has, and "imported with
rejections" is not "success": `0` only when every data row imported (silent
dedupes do not count against it); `1` when any row was rejected, any
domain was refused (the valid rows still imported — the summary says
exactly what happened), or the file was refused. Rejects print to stderr
one per line as `line N: <token> — <why>`, refusals one per host as
`refused: <host> is <state>. … Its rows were skipped.`; stdout carries the
summary and `run N started from <path>`.

### Acceptance

- [ ] A file with one bad row imports the rest and names the failure — file
      line and token; the bad row aborts nothing.
- [ ] The header contract holds: the three spellings parse; anything else
      refuses the file naming what was expected.
- [ ] Exact duplicates dedupe silently; same-host setting conflicts reject
      the later row naming both values and the earlier line.
- [ ] Nothing in the parser can make a network call — import allowlist and
      socket-block both proven by test; host validation is syntax-only.
