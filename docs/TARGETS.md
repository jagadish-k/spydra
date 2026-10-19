# Target domains

**BUILD_PLAN 1.3.** Example sites for the operator to point the crawler at by
hand once the UI exists (phase 3), recorded 2026-10-18.

**Nothing in the build depends on this file.** Phases 1 and 2 are proven
against the local fixture site (`1.4`) and never touch the public internet —
the crawler is generic, so a phase gate that needs a third party's uptime,
markup and tolerance fails for reasons unrelated to the code. One of the three
below started returning 403 within a day of being recorded, which is the
argument made for us.

This file is a **record of a decision**, not an enforcement mechanism. The
crawler fetches and honours `robots.txt` at run time, once per domain per run
(spec 002 §5), and a `Crawl-delay` there raises the configured delay whatever
this file says. Everything below was read by hand on **2026-10-18** and will
drift; the live file wins.

> **These three are examples, not production targets.** Two of the three
> terms-of-use documents could not be retrieved at all and the third only
> through a third-party tracker (below); the operator reviewed that and chose
> to proceed on that basis, for manual trials only.
>
> **Nothing here is legal advice, and this note does not survive promotion.**
> Anything that becomes a production target — crawled on a schedule, its data
> relied on — needs its live terms read first. The gap is recorded per domain
> below so that conversation starts from facts.

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

|                 |                                                         |
| --------------- | ------------------------------------------------------- |
| **Render mode** | `rendered` — **measured**                               |
| **robots.txt**  | permits the seed path                                   |
| **Terms**       | **retrieved only via a third-party tracker; see below** |

- **Rendering.** The server returns an application shell: _"You need to
  enable JavaScript to run this app."_ Zero product tiles in the response.
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
  document with inconsistent dating. The operator has reviewed this and
  accepted it **for development use**: the browser-only licence and the
  database right are recorded here rather than treated as a blocker. They
  become one again if this domain is ever promoted beyond an example.

### 2. Rapid Electronics — `rapidonline.com`

Seed: `https://www.rapidonline.com/cables-wires`

|                 |                                       |
| --------------- | ------------------------------------- |
| **Render mode** | `rendered` — **measured**             |
| **robots.txt**  | permits the catalogue                 |
| **Terms**       | **not read — could not be retrieved** |

- **Rendering.** The seed returns _"Javascript is currently disabled"_ and
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

|                 |                                       |
| --------------- | ------------------------------------- |
| **Render mode** | `auto` — see below                    |
| **robots.txt**  | **`Crawl-delay: 60`**                 |
| **Terms**       | **not read — could not be retrieved** |

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

## What reading these three changed

Recorded because the findings outlived the dependency, not as live blockers:
nothing below gates a task any more.

**All three are JavaScript-rendered**, measured rather than assumed — none
returns product tiles in its server HTML, where `1.3` had asked for two
static and one rendered. That mattered while the fixture corpus was meant to
be _captured_ from them: HTML cannot be recorded from a JS-rendered page
without the render sidecar, so the fixture task would have had to wait on the
fetcher that was supposed to consume it. The fixtures are hand-written now
(`1.4`, `TESTING.md` §4) and the circularity is gone.

**None emits `schema.org/Product`**, so the `structured` rung (spec 003 §1)
has no example here. An earlier note in this file argued that a hand-written
JSON-LD fixture would make rung 1 "an untested rung dressed as a tested one".
That was the right worry about the wrong thing, and it is worth being
explicit about the reversal: a written fixture fully tests **the parser**,
which is what the build can test. What it cannot tell you is how many real
pages carry JSON-LD — and that is an operator-time observation on whatever
sites they choose, not something any fixture could have settled. Rung 1 is
cheap and tried first precisely because its coverage is unknowable in
advance.

**`activemotif.com` publishes `Crawl-delay: 60`.** Spec 002 §5 treats that as
a floor, so one page per minute. Harmless now that no phase exits against it,
but worth knowing before anyone points a real run at it.
