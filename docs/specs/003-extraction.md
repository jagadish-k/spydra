# 003 — Extraction chain and validation

**Phase 1** · depends on 001 · ADR-0005

Extraction is an ordered chain of strategies, cheapest first. Each rung is
tried only if the previous produced nothing usable. Ordering is the whole
design: it reduces how often the expensive rungs are invoked.

---

## 1. The chain

```
1. structured   JSON-LD (schema.org/Product), microdata, RDFa
2. selector     the domain's approved template for this URL pattern
3. llm_proposal only during onboarding/review — never at crawl time
4. unknown      routed to the review inbox with a reason
```

```python
class ExtractionStrategy(Protocol):
    name: Strategy
    async def extract(self, page: FetchedPage, template: Template | None
                      ) -> ExtractedFields | None: ...
```

`chain.py` owns the order. Adding a strategy means adding a class and one
entry in the chain — this is what the open/closed principle buys here, and the
only place it is worth the indirection.

**Rung 1 matters more than it looks.** Where a site emits
`schema.org/Product`, structured data is more stable than CSS selectors,
survives redesigns, and needs no model. These are bespoke supplier
catalogues so coverage will be low — JSON-LD is a consumer-SEO feature — but
it is free to try and it is the cheapest rung.

Use `extruct` for rung 1; do not hand-roll JSON-LD parsing.

## 2. Selector extraction

Per `FieldRule` (see spec 001). Note that `required` is **inert** — see §3
and [ADR-0027](../adr/0027-no-required-fields.md):

```
resolve(selector) → nodes
  ├ many=false → first node, or None
  └ many=true  → all nodes
extract(attr)    → 'text' (normalised whitespace) or attribute value
transform(...)   → applied in order
validate(...)    → records pass/fail, never raises
```

Parsing uses **selectolax** (`LexborHTMLParser`) — roughly an order of
magnitude faster than BeautifulSoup and sufficient for CSS selection. Reach
for lxml only if XPath is genuinely needed.

**Transforms** are small pure functions, composed in order:

| Transform        | Behaviour                                                     |
| ---------------- | ------------------------------------------------------------- |
| `trim`           | collapse whitespace, strip                                    |
| `strip_currency` | remove symbol and thousands separators, keep sign and decimal |
| `parse_decimal`  | to `Decimal`; fails loudly on ambiguity                       |
| `absolute_url`   | resolve against the page URL                                  |
| `first` / `all`  | cardinality                                                   |
| `pairs(th, td)`  | a spec table to a key/value mapping for JSONB                 |

Currency detection: symbol first, then the page's declared currency, then the
domain default. A price without a determinable currency is a **validation
failure**, not a guess.

## 3. Validation

Every extracted field is checked at crawl time. Validation never raises — it
records.

| Rule              | Passes when                                     |
| ----------------- | ----------------------------------------------- |
| `non_empty`       | after trim, length > 0                          |
| `currency`        | parses to a Decimal and has a 3-letter currency |
| `url`             | absolute, http(s)                               |
| `integer`, `date` | parses                                          |
| `min_count(n)`    | a `many` field yielded at least n               |
| `matches(re)`     | matches the pattern                             |

Results land in `page_observations.validation` as
`{field: {"rule": "currency", "ok": false, "saw": "POA"}}`.

**Routing** (amended by [ADR-0027](../adr/0027-no-required-fields.md)):

- **No field is ever `required`**, so a per-field validation failure does not
  route and does not halt. It is recorded in
  `page_observations.validation` and is evidence for the operator, not
  control flow. The observation is written with whatever resolved; partial
  data is never discarded.
- **`empty_extraction` is the only reason a page reaches `unknown_pages`
  from this path**: a 200 response from which no field resolved to a
  non-empty value. This is the redesign signature, and the diff against the
  last working observation is what the operator needs.
- **`empty_extraction` exceeding 20% of a domain's pages in a run** → the
  domain moves to `broken` and **crawling stops for it mid-run**. Carrying on
  and recording thousands of empty extractions is how a redesign quietly
  corrupts a dataset.

  **Only pages with a prior non-empty observation count toward that 20%**
  ([ADR-0030](../adr/0030-empty-needs-a-prior.md)). A regression is a
  _change_, and a page that never yielded anything cannot have changed — so a
  soft 404 (HTTP 200, "product not found", no content) is reported in the
  inbox and excluded from the threshold. Without that exclusion a catalogue
  with more than 20% dead links halts itself on every run and reports a
  redesign that never happened, and dead links are ordinary.

- **A FIRST run with more than 20% empty → `awaiting_approval`, not
  `broken`.** Nothing has a prior observation, so no page can evidence a
  regression; what the run shows is that the template never worked — approved
  against a few samples, met the real catalogue. `broken` means "this used to
  work", and sending it there would hide the actual problem behind the wrong
  state (ADR-0030).

  Read ADR-0027 before re-attaching this threshold to per-field validation.
  Counted that way it never fires, because nothing is required — and a
  redesign then fills the dataset silently, which is the one failure this
  section exists to catch.

**One predicate, three consumers.** `empty_extraction` decides the
`unknown_pages` reason, the `broken` threshold above, and the `auto`
render-mode fallback (spec 012 §4). It is one function in
`extraction/validation.py` and three call sites, so they cannot disagree
about what "nothing came back" means.

This is the system's most important failure mode: it produces no error and no
crash, just wrong data. Validation is mandatory per field, not optional.

## 4. Content hashing

`content_hash` is computed over the **normalised extracted fields**, not the
raw HTML. Raw HTML changes on every request because of timestamps, session
tokens and CSRF fields; hashing it would mark every page changed every run.

Normalisation: sorted keys, decimals canonicalised, whitespace collapsed,
asset URLs excluded (they are hashed separately by content).

If the hash matches the previous observation, write a lightweight row
(`observed_at`, `http_status`, `unchanged = true`) or skip and bump
`pages.last_crawled_at` — configurable per domain.

`page_current` skips `unchanged` rows (spec 001 §1), so current state is the
last full observation. When nothing survives normalisation (an empty page,
or one whose only field is an asset URL) there is **no hash**:
`content_hash` is NULL and the row is never `unchanged`, because "nothing to
compare" is not "the same as before".

## 5. Acceptance

- [ ] A page with valid JSON-LD extracts via `structured` without consulting a
      template.
- [ ] The same page with JSON-LD removed falls through to `selector`.
- [ ] A field failing validation is **recorded** in
      `page_observations.validation`, writes the observation, and does
      **not** route to `unknown_pages` or halt the domain (ADR-0027).
- [ ] A template declaring `required: true` is **rejected** by the loader
      rather than ignored (ADR-0027, BUILD_PLAN 1.14).
- [ ] 21% of a domain's pages yielding `empty_extraction` **where each had a
      prior non-empty observation** moves the domain to `broken` and halts
      it; 19% does not.
- [ ] A page that has never extracted anything is reported as
      `empty_extraction` and does **not** count toward the threshold, so a
      domain whose links are 50% dead keeps crawling (ADR-0030).
- [ ] A first run with 21% empty moves the domain to `awaiting_approval`
      rather than `broken`.
- [ ] Re-extracting an unchanged page produces an identical `content_hash`.
- [ ] A price of "POA" is a validation failure, not `0.00`.
- [ ] Transform chains are unit-tested against a table of fixtures, including
      European decimal commas and multi-currency pages.
