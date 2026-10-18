# Target domains

**BUILD_PLAN 1.3.** The first real sites this crawler points at, confirmed by
the operator on 2026-10-18. Phases 1 and 2 both exit against these.

This file is a **record of a decision**, not an enforcement mechanism. The
crawler fetches and honours `robots.txt` at run time, once per domain per run
(spec 002 §5), and a `Crawl-delay` there raises the configured delay whatever
this file says. Everything below was read by hand on **2026-10-18** and will
drift; the live file wins.

> **Nothing here is legal advice.** Two of the three terms-of-use documents
> could not be retrieved at all (below). The operator confirmed these targets
> with that gap open and on the record.

---

## Operator policy for these domains

**No field is marked `required`.** Confirmed by the operator: gather whatever
resolves, and leave the rest to human triage.

The consequences are worth stating, because they change what a healthy run
looks like:

- `FieldRule.required` already defaults to `false` (spec 001 §3), so this is a
  **template-configuration policy, not a change to the spec or the schema.**
  Spec 003 §3's required-field routing stays implemented and stays tested —
  `TESTING.md` §2 asks for it by name, and it is the mechanism rather than the
  configuration that those tests cover. The YAML templates for these three
  domains simply set nothing required.
- So `unknown_pages` will not fill with `validation_failed`. The reason that
  still fires is **`empty_extraction`** — every field resolving to nothing on
  a 200 — and that is the one the operator needs, because it is the redesign
  signature (spec 003 §3).
- The 20%-failures-to-`broken` rule is therefore driven by
  `empty_extraction`, not by per-field validation. A domain whose prices are
  simply absent — see Active Motif — stays `active` and reports empty price
  fields, rather than halting itself mid-run over a catalogue that never had
  prices to find.

**If this should become a global rule** rather than a per-domain
configuration — the YAML loader refusing `required: true`, say — that is a
change to spec 003's stated behaviour and wants an ADR. It is deliberately
not one today.

---

## The three targets

### 1. Thermo Fisher Scientific — `thermofisher.com`

Seed: `https://www.thermofisher.com/search/browse/category/in/en/80013650`

| | |
| --- | --- |
| **Render mode** | `rendered` — **measured** |
| **robots.txt** | permits the seed path |
| **Terms** | **retrieved only via a third-party tracker; see below** |

- **Rendering.** The server returns an application shell: *"You need to
  enable JavaScript to run this app."* Zero product tiles in the response.
  Confirmed on the seed URL.
- **robots.txt.** No `Crawl-delay`. `/search/browse/` is **not** disallowed.
  Disallowed and relevant to crawling: `/search/global/miniPDPAction*`,
  `/search/global/viewAllSizesAction*`, `/search/global/searchAction*`,
  `/search/supportSearch`, `/search/results*`, `/content/`,
  `/etc/countries/`, `/order/spectra-viewer/`, `/order/oligoDesigner/`,
  `/order/assay-builder/`, `/order/alignMap-server/`,
  `/antibody/primary/query/`, `/antibody/secondary/query/`. Nine sitemaps
  published. One named-agent group (`Slurp`), which does not apply to us.
- **Terms — the open question on this domain.** The Terms of Use page could
  not be fetched directly. A third-party terms tracker's capture (version
  #854540, observed 2026-03-17, with the document itself dated 2016-06-17 and
  the tracker's own header showing conflicting dates) contains **no explicit
  anti-scraping clause**, but two provisions bear on this directly:
  - §2 grants a "non-exclusive, non-transferable, revocable license to access
    the Site **via an industry-standard web browser**". A crawler is not a
    browser, so the permission the document grants arguably does not cover
    this use.
  - §4 reserves all intellectual property rights including **"rights in and
    to databases"**, and the document reserves the right to block users and
    IP addresses.

  That is indicative, not authoritative: it is a third party's capture of a
  document with inconsistent dating. **Read the live Terms of Use before this
  domain goes `active`.**

### 2. Rapid Electronics — `rapidonline.com`

Seed: `https://www.rapidonline.com/cables-wires`

| | |
| --- | --- |
| **Render mode** | `rendered` — **measured** |
| **robots.txt** | permits the catalogue |
| **Terms** | **not read — could not be retrieved** |

- **Rendering.** The seed returns *"Javascript is currently disabled"* and
  unrendered template placeholders (`{{SessionBasket.ItemCount}}`). Nine
  **category** tiles are present server-side; **no product tiles**. An
  earlier note in this project had this domain down as static — that was
  wrong, and inferred from its not-found page rendering as HTML rather than
  from a listing.
- **robots.txt.** No `Crawl-delay`. Catalogue paths permitted. Disallowed:
  `/checkout`, `/myaccount`, `/downloads/`, `/api`, `.aspx` pages, catalogue
  images, print versions, some filtered-search URLs, landing-page tests and
  the audience-set path. Sitemap index at
  `https://static.rapidonline.com/sitemap-index.xml`.
- **Terms.** Not read. `/terms-and-conditions` and `/terms-conditions` both
  failed to retrieve. **Unresolved.**

### 3. Active Motif — `activemotif.com`

Seed: `https://www.activemotif.com/`

| | |
| --- | --- |
| **Render mode** | `auto` — see below |
| **robots.txt** | **`Crawl-delay: 60`** |
| **Terms** | **not read — could not be retrieved** |

- **Rendering.** The closest of the three to server-rendered: category names
  and facet counts are present in the response and there is no
  JavaScript-required message. But a category page
  (`/catalog/9/chromatin-immunoprecipitation`) returns navigation and facets
  with **zero product tiles**, so the product grid itself is not in the
  server HTML. `auto` is the honest setting: fetch cheaply, fall back to the
  browser when the fields do not resolve (spec 001 §3), and pin it from
  observed behaviour after a few runs rather than guessing now.
- **robots.txt.** **`Crawl-delay: 60`.** Spec 002 §5 treats that as a floor,
  so this domain is crawled at **one page per minute** — `crawl_delay_ms`
  cannot go below 60000 for it. That is not a defect to work around; it is
  the site's stated rate and the reason the politeness gate exists. It does
  mean any end-to-end demonstration against this domain is measured in hours,
  which matters for the phase-1 and phase-2 exit criteria.
  Also disallowed: the cart, internal search, and `/catalog/561`,
  `/catalog/565`, `/catalog/806` including their query-string variants.
  Sitemap published.
- **No prices.** No price strings appear anywhere in the HTML read so far,
  and no "request a quote" text either. Life-sciences catalogues commonly
  quote rather than publish. With no required fields this is harmless: the
  domain stays `active` and reports empty price fields for the operator to
  look at.
- **Terms.** Not read. `/terms` and `/terms-of-use` both failed to retrieve.
  **Unresolved.**

---

## Deviations from BUILD_PLAN 1.3, on the record

**1.3 asks for "two static, one JS-rendered". These are three
JS-rendered.** Measured, not assumed: none of the three returns product
tiles in its server HTML. The operator confirmed them anyway. Two
consequences follow, and neither is cosmetic:

1. **The `selector` rung has no cheap target.** Spec 003 §1's rung 2 was
   meant to be exercised against static markup. Here every page reaches it
   only after a render, so the static path (`HttpxFetcher`, 1.7) is proven by
   the `auto` fallback on Active Motif and by fixtures, not by a domain that
   is genuinely static end to end.
2. **1.4's fixture corpus now depends on 1.8.** Recorded HTML cannot be
   captured from a JavaScript-rendered page without the render sidecar, so
   the fixture task that was supposed to gate lane C now waits on lane B.
   **This inverts the plan in the phase-1 brief** and needs sequencing before
   lane C starts. The alternatives are to capture fixtures by hand from a
   browser for now, or to add one genuinely static domain.

   `ooznest.co.uk` was verified during target research as server-rendered
   with product titles **and** prices in the response, and its robots.txt
   permits the catalogue. It is not a target; it is the one candidate that
   would close this gap if the operator wants it.

**No structured data.** None of the three emits `schema.org/Product`, so
spec 003 §1's `structured` rung and the first acceptance criterion in §5 have
no real fixture from these domains. A synthetic JSON-LD fixture would make
rung 1 an untested rung dressed as a tested one; flagged rather than faked.
