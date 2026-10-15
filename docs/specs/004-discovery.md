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
  "next_page":         "a[rel='next']",
  "product_links":     "a.product-card__link",
  "subcategory_links": "nav.cat-tree a",
  "allow_patterns":    ["^/catalog/", "^/products/"],
  "deny_patterns":     ["\\?(colour|grit|sort|view|per_page)=", "/compare"],
  "max_depth":         5
}
```

Each extracted link is kept only if **all** hold:

1. Same registrable domain as the seed (subdomains configurable per domain).
2. Scheme is http or https.
3. Matches at least one `allow_pattern` if any are set.
4. Matches no `deny_pattern`.
5. Depth below `max_depth`.
6. Not already in `crawl_queue` for this run (`UNIQUE (run_id, url_hash)`).

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
2. **Per-run URL cap per domain**, default 20,000. On breach the domain halts
   for that run and the report names the pattern that exploded, grouped by
   the discovery rule that matched it.
3. **Depth cap**, default 5.
4. **Repeating-path detection** — `/a/b/a/b/a/` means a relative-link bug on
   the site; reject at three repetitions.

Also reject: `mailto:`, `tel:`, `javascript:`, URLs over 2,000 characters,
and anything matching a calendar pattern (`/20\d\d/\d\d/`) unless explicitly
allowed.

## 4. Dry-run discovery

Exposed on the template review screen as a button. It crawls **one** listing
page and returns exactly what would be enqueued, grouped by the rule that
matched:

```json
{
  "matched": {
    "product_links":     {"count": 48, "sample": ["/products/flap-disc-120g-115mm", "..."]},
    "next_page":         {"count": 1,  "sample": ["/products/abrasives?page=2"]},
    "subcategory_links": {"count": 11, "sample": ["..."]}
  },
  "rejected": {
    "deny_pattern": {"count": 312, "pattern": "\\?(colour|grit|sort)=", "sample": ["..."]},
    "off_domain":   {"count": 7,   "sample": ["..."]}
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
