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
8. Its canonical path does not match a calendar pattern (`/20\d\d/\d\d/`)
   unless an `allow_pattern` matched — the operator's explicit yes outranks
   the calendar defence (§3).
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
characters, and anything matching a calendar pattern (`/20\d\d/\d\d/`) —
unless an `allow_pattern` matched it: the calendar check runs after the
allow check, so the operator's reviewed pattern is the explicit permission
(a broad allow implicitly permits calendars; the dry-run is where that
becomes visible).

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

Check this with the dry-run before building anything: crawl one category page
with `subcategory_links` unset and compare `projected_urls_at_depth_5` against
the run with it set. **If the two sets match, delete the rule.** Most of the
time they do.

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
      "sample": ["/products/flap-disc-120g-115mm", "..."]
    },
    "next_page": { "count": 1, "sample": ["/products/abrasives?page=2"] },
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
  "projected_urls_at_depth_5": 2140
}
```

This is where a facet trap is caught before it generates 40,000 URLs, and it
is far cheaper than catching it mid-run.

## 5. Acceptance

- [ ] `?b=2&a=1` and `?a=1&b=2` produce the same `url_hash`.
- [ ] `utm_source` is stripped; a meaningful `?page=2` is not.
- [ ] A seed with a faceted listing is capped by `deny_patterns` and the
      dry-run reports the rejected count.
- [ ] Depth 6 links are not enqueued when `max_depth` is 5.
- [ ] A run breaching the per-domain URL cap halts that domain and names the
      pattern.
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
