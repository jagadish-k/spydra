# feat/1.11-observation-writes

**Task:** BUILD_PLAN `1.11` · **Spec:** `specs/003-extraction.md` §4,
`specs/001-domain-model.md` §1–2
**ADRs:** **0007 (append-only)**, **0027 (no required fields)**,
**0030 (empty needs a prior)**, 0004, 0008, 0014

**Goal.** Turn a `ChainResult` into a row. `content_hash` over the
**normalised extracted fields**, never the markup. Route an
`empty_extraction` to `unknown_pages`. Count regressions ADR-0030's way —
only pages with a prior non-empty observation — and move the domain to
`broken` past 20%, or to `awaiting_approval` on a first run, where nothing
can have regressed yet.

**This is the slice BUILD_PLAN `5.6` calls "the only thing standing between
a redesign and silent data corruption".** The detector is here; the report is
phase 5.

---

## Measured before writing anything

1. **`page_observations` has no `unchanged` column.** Spec 003 §4 requires
   writing one (`observed_at`, `http_status`, `unchanged = true`) and the
   `Observation` entity has carried an `unchanged: bool` since `1.2` — but
   spec 001 §1's DDL does not list it and neither does `tables.py`. The
   entity field has been unwritable for three slices. Added here.
2. **Nothing persists the emptiness verdict**, so the `broken` threshold's
   query would have to recompute it in SQL — a **fourth** definition of
   `empty_extraction` against ADR-0027's "one function, three callers", and
   the one most likely to disagree (`attributes = '{}'::jsonb` is not the
   same question as `all(is_empty(v))`). Persisted as a column instead,
   computed once in Python.
3. **ADR-0030's own prescription is unreachable in the lifecycle.**
   "A first run in which more than 20% of pages are empty moves the domain to
   `awaiting_approval`" — there is no `active -> awaiting_approval` edge in
   `lifecycle.py` or in spec 001 §2's diagram. Legal events from `ACTIVE` are
   PAUSE, BLOCK, BREAK, ARCHIVE. The accepted ADR needs an edge that was
   never drawn; added here as its own event, raised below.
4. **The price composite carries `raw`** — the pre-transform text, which
   exists for validation evidence (`{"rule": "currency", "saw": "POA"}`).
   Hashing it makes `£10.50` -> `GBP 10.50` a content change on a page whose
   price did not move, which is precisely the churn spec 003 §4 rejects raw
   HTML for. Excluded from the hash, below.
5. **A lightweight `unchanged` row has no fields, so the predicate reads it
   as empty.** `empty_extraction(200, {})` is `True` by definition — every
   stable page on a stable site would score as empty, each with a non-empty
   prior and therefore each a _regression_, and a site that never changes
   would halt itself as a redesign on its second run. The worst bug
   available in this slice. The fix is an ordering (below), and a mutation
   proves the ordering.
6. **`page_current` goes stale on any column-adding migration.** ADR-0007
   makes the view the only way anything reads current state, and Postgres
   expands `SELECT *` at CREATE time. Measured on the dev database: three
   columns added, the view still carried twenty — no error, no warning. Every
   reader (the review inbox, `5.6`'s broken-template report) would have
   queried a shape missing the column the report is about. Found while
   proving the migration, not by review.
7. **Assessed after every page, the first page of a run is a ratio of one.**
   Spec 003 §3 halts a domain mid-run, so the verdict is re-read per page —
   and a five-page run whose FIRST page was its one redesigned page halted
   the domain at 100%, two pages before the same run settled at 20% and
   should not have halted at all. Measured as two test failures. A false
   `broken` needs a human to clear it (ADR-0004), which is the "loud
   recurring failure" ADR-0030 refused to trade for.

## Decisions

- **`content_hash = sha256(canonical_json(normalised_fields))`.**
  Normalisation is spec 003 §4's list, implemented literally: keys sorted,
  whitespace collapsed to single spaces, `Decimal` canonicalised through
  `format(d.normalize(), "f")` (so `10.50`, `10.5` and `1.05E+1` are one
  hash, and `100` does not become `1E+2`), nested mappings and sequences
  recursed.
- **Empty values are dropped before hashing**, using `is_empty` — the same
  function the predicate is built on, not a second notion of empty. A field
  that resolved to nothing is nothing: without this, adding a field to a
  template that matches on no page would change the hash of every page in
  the domain and report the whole catalogue as changed.
- **`raw` is dropped from the price composite before hashing.** Finding 4.
  It is evidence, not data.
- **Asset URLs are excluded by value, not by field name.** The first draft
  of this task file claimed there was nothing to exclude in phase 1 because
  `1.12` resolves images from the markup rather than into `ExtractedFields`.
  That is wrong, and `1.4`'s own template says so: it defines an `images`
  field (`.gallery__image[src]`, many). So the exclusion is code. The filter
  is "a value that normalises to an absolute http(s) URL", because a
  hardcoded list of names (`images`, `image_urls`, `thumbnail`) would invent
  the vocabulary `field_vocabulary` defines in phase 4 and would miss the
  fifth name a template picks. **Its cost, stated:** a URL-valued field that
  is genuinely data cannot contribute to change detection either.
- **The emptiness verdict is written, not derived** (finding 2), and it is
  **computed before the fields are emptied** (finding 5). That ordering is
  the whole guard. The first implementation also copied the predecessor's
  verdict onto the lightweight row; mutation proved that line could not
  fail — it agreed with the computed verdict in every reachable case — and
  it was the wrong answer in the corner where they differ: a page whose only
  field is an asset URL normalises to `{}`, so it hashes like an empty page
  while the predicate correctly says it has content. Inheriting would have
  reported a page with content as a regression. Removed; a test pins the
  corner.
- **A verdict needs five pages**, and the number is derived rather than
  picked (finding 7): `1/n > 0.20` holds for every `n < 5`, so five is the
  smallest sample at which one page cannot halt a domain by itself. Spec 003
  §3 names no minimum — raised below.
- **`page_current` is recreated by the migration** (finding 6), from
  `tables.py`'s one definition rather than a second copy, and
  `test_schema.py` now holds the view's columns equal to the table's so the
  next column-adding migration cannot forget it.
- **`strategy` keeps spec 012 §4's `static_fallback`; the rung goes in a new
  `extraction_rung`.** `1.7`'s open question 2 lands here: `Strategy`
  answers two questions and one column holds one answer. Writing the rung
  into `strategy` contradicts three documents (spec 012 §4, spec 001 §1,
  TESTING.md §2); writing only `static_fallback` loses which rung ran, so a
  render-down run reports zero selector and zero structured extractions.
  Both facts are recorded, which costs one redundant column in the
  non-degraded case and keeps the structural call open for the human — it is
  a read-side change whichever way that goes.
- **A first run that never matched is its own event**, `NEVER_MATCHED`,
  `ACTIVE -> AWAITING_APPROVAL`. Not `RE_REVIEW` (the operator's edge out of
  `BROKEN`) and not `BREAK` (which means "this used to work", the very
  distinction ADR-0030 exists to draw). `DomainEvent`'s own docstring gives
  the reason: the lifecycle is keyed on events so the run report can tell
  two causes of one edge apart.
- **The denominator is pages crawled in this run for this domain**, counted
  distinct — ADR-0030's `count(regression) / count(pages crawled)`. Not
  observations: two observations of one page would otherwise dilute the
  ratio, and `1.13`'s retry path produces exactly that.
- **The threshold lives in `domain/health.py`, not in `observations/`.** It
  was written there and moved: the adapter has to name `RunHealth` (it
  produces one), the writer has to import the adapter, and the package
  `__init__` re-exported both — a circular import the test run raised and
  review would not have. The placement with no cycle is also the honest one:
  a pure function over counts returning a `DomainEvent` is
  `lifecycle.transition`'s shape exactly. `spydra.observations` is added to
  the domain's forbidden-import list while this is fresh.
- **The threshold is a pure function** over three numbers, with the SQL that
  produces them in the adapter. 21%-trips/19%-does-not is then arithmetic
  that cannot be flaky, and the counting query is tested separately against
  real rows.
- **No speculative index.** The prior-observation lookup is served by spec
  001 §1's existing `(page_id, observed_at DESC)`. A partial index on
  non-empty priors is an obvious next move and is not added without a
  measurement that asks for it.

## Files this slice owns

```
backend/spydra/domain/enums.py                        (NEVER_MATCHED)
backend/spydra/domain/lifecycle.py                    (one edge)
backend/spydra/domain/entities.py                     (Observation: 2 fields)
backend/spydra/extraction/hashing.py                  (NEW)
backend/spydra/domain/health.py                       (NEW - pure, ADR-0030)
backend/spydra/observations/writer.py                 (NEW - the use case)
backend/spydra/adapters/postgres/observations.py      (NEW - the SQL)
backend/spydra/adapters/postgres/tables.py            (3 columns)
backend/migrations/versions/<rev>_observation_writes.py  (NEW)
backend/spydra/extraction/validation.py               (is_empty takes object)
backend/tests/extraction/pages.py                     (NEW - shared fixtures)
backend/tests/extraction/test_chain.py                (imports them)
backend/tests/extraction/test_hashing.py              (NEW)
backend/tests/domain/test_health.py                   (NEW)
backend/tests/adapters/postgres/observation_seed.py   (NEW)
backend/tests/adapters/postgres/test_schema.py        (the view-parity guard)
backend/tests/test_import_contracts.py                (one prefix)
backend/tests/adapters/postgres/test_observations.py  (NEW)
docs/BUILD_PLAN.md                                    (tick 1.11)
```

## Done when (BUILD_PLAN 1.11, spec 003 §5)

- [x] Re-extracting an unchanged page yields an identical `content_hash` —
      through the real chain over `1.4`'s fixture, twice, not through a
      literal hashed twice.
- [x] `northfield/product-redesigned.html` trips `broken` (2 of 5); any
      number of `mertens/product-missing.html` does not (10 of 11 empty, zero
      regressions, still `active`), and both in one run tell apart.
- [x] 21% trips the threshold, 19% does not — through the real counting query
      over 100 pages, and at the boundary in `test_health.py`.
- [x] An `empty_extraction` on a 200 lands in `unknown_pages` whether or not
      it counts toward the threshold.
- [x] A first run past 20% goes to `awaiting_approval`, not `broken`.
- [x] Mutation: **33 mutations, all red.** The first pass left four green,
      three of which were tests passing for the wrong reason (a 404 test that
      did not need the status guard; a prior-lookup that no test gave equal
      timestamps; a per-domain ratio no test gave two domains) and one of
      which was production code that could not fail — the inherited verdict
      above.
- [x] `make check` green, 421 tests.

## Open questions

1. **`strategy` versus `extraction_rung`** — `1.7`'s open question 2, now
   with rows behind it. This slice records both rather than choosing, so the
   choice stays reversible: `static_fallback` remains in `strategy` as three
   documents say, and the rung is its own column. The clean shape is
   probably `strategy = <rung>` plus a `degraded BOOLEAN`, which needs an
   ADR because it changes what spec 012 §4 and TESTING.md §2 assert.
   **For the human.**
2. **Spec 001 §2's diagram has no `active -> awaiting_approval` edge** that
   accepted ADR-0030 requires (finding 3). Implemented; the diagram and
   ADR-0030's `Amends:` list are documentation this slice does not own.
   **For the human.**
3. **Spec 003 §4's "configurable per domain"** — whether an unchanged page
   writes a lightweight row or skips and bumps `pages.last_crawled_at` — has
   no column to be configured in. This slice implements the lightweight row
   unconditionally, which is the branch that keeps ADR-0007's history
   complete and the one the `unchanged` column exists for. A
   `domains.unchanged_policy` is a schema decision. **For the human.**
4. **The asset-URL exclusion is by value** (above), so a URL-valued field
   that is genuinely data — a link to a manufacturer's page — is invisible to
   change detection. The field vocabulary in phase 4 is where a field can
   declare which it is; until then the alternative is a hardcoded name list,
   which is worse. **For the human.**
5. **`MINIMUM_PAGES_FOR_A_VERDICT = 5` is in no spec.** Spec 003 §3 halts
   mid-run and names no minimum sample, so without one the first page of
   every run is a 100% verdict (finding 7). Five is derived — the smallest
   sample at which one page cannot halt a domain — but "one page is not
   enough" is itself a judgement, and a larger minimum (20, where the 20%
   threshold starts meaning what it says) is defensible. It wants a line in
   spec 003 §3 either way. **For the human.**
6. **A simultaneous observation is not an earlier one.** ADR-0030's prior
   lookup is a strict `observed_at <`, so two observations of one page
   sharing a timestamp carry no order and neither is the other's prior. That
   is the conservative reading — a false `broken` costs a human — and it is
   now a test. If `1.13` ever writes two observations of one page inside one
   timestamp, the honest fix is to order on the append-only `id`.
   **For the human.**
