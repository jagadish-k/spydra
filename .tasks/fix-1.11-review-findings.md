# fix/1.11-review-findings

**Task:** BUILD_PLAN 1.10/1.11 follow-up: three blocking and eleven
non-blocking findings from a fresh-context review of the merged slices.
**Spec:** 003 §1–§4, 001 §1 · **ADRs that constrain this:** 0007
(append-only, `page_current`), 0027 (one emptiness predicate, no required
fields), 0030 (the threshold counts regressions only).

Stacked on `claude/quirky-hypatia-kafanj` (#17, the pre-push hook) so it
inherits the gate fix. Merge #17 first.

## Measured before fixing

Throwaway test against real Postgres, through the real chain and writer.
Deleted before commit.

| Finding | Measurement                                                                                                                                                                                                |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1      | Stable product page, two runs → `page_current` = `(title NULL, price NULL, unchanged true)`                                                                                                                |
| B2      | Three no-template pages, first run → `RunHealth(pages_crawled=3, empty_pages=3)`. Expected `(0, 0)`                                                                                                        |
| B3      | JSON-LD `Product` with only `image`, plus the approved template's markup → chain returns `structured {'images': [...]}`. Both rows have NULL title and price. Run 2 is `unchanged`. No `unknown_pages` row |

## Decisions (made, not asked: raised below for the human)

**B1: `page_current` excludes `unchanged` rows** (`WHERE NOT unchanged`),
via a new migration that drops and recreates the view.

- An `unchanged` row asserts "same content as the prior hash", so the newest
  non-`unchanged` row _is_ the current content.
- Recency is already on `pages.last_crawled_at`.
- Rejected:
  - **Stop nulling fields on an unchanged row.** It contradicts spec 003
    §4's "lightweight row" and stores every stable catalogue twice per run.
  - **"Skip and bump `last_crawled_at`"** (spec 003 §4's other branch).
    This one is wrong for a reason beyond the spec. ADR-0030's denominator
    is pages _observed this run_, so a skipped stable page would vanish from
    `pages_crawled`. Then three regressions among 3,400 stable pages would
    read 3/3 = 100% and halt a healthy domain. It would also leave
    `asset_queue` nothing to hang off.
- The migrations that created the view earlier (`8c1d4a9f5e02`,
  `156197f778f8`) imported `PAGE_CURRENT_SQL` from `tables.py`. That makes
  history depend on the present: with the constant now naming `unchanged`,
  `8c1d4a9f5e02` would fail on a fresh database, because the column arrives
  two revisions later. Each old migration now carries a frozen literal of
  the definition it shipped; `tables.py` holds the current one.

**B2:** `AND o.template_id IS NOT NULL` in `_HEALTH`'s `final` CTE.
ADR-0027 §3 excludes no-template pages "neither as empty nor as
crawled-successfully".

**B3: "substantive" = something survives `normalise`.**

- `hashing.is_substantive(fields)` is `bool(normalise(fields))`, the same
  normalisation the hash uses, so the two notions cannot drift.
- The chain keeps trying rungs while the result is not substantive. It
  remembers the first result that is not an empty extraction (ADR-0027's
  predicate, unchanged) and returns it if no rung does better. So the
  template gets its chance, and an image-only stub's URLs still reach
  `1.12`'s enqueue when it is all there is.
- `content_hash()` returns `None` when nothing survives normalisation.
  `unchanged` requires a non-NULL hash on both sides, so "nothing
  comparable" can never be recorded as "unchanged".
- This flips `test_a_page_whose_only_field_is_an_asset_url_is_not_empty`'s
  hash assertion (it pinned `content_hash == content_hash({})`) on purpose.
  That page is still **not** `empty_extraction`: an image URL is a field
  that resolved, and ADR-0027's predicate is untouched.
- It also closes non-blocking 6d. `unchanged` and `empty_extraction` can no
  longer both be true, because every empty extraction is non-substantive.

## Non-blocking, all fixed here except 6e

1. `strip_currency` destroyed currency detection. `_price` now detects from,
   and records as `raw`, the **pre-transform** text.
2. Three more notions of "empty". `ChainResult.empty` is deleted (dead).
   `structured.py`'s `v not in (None, [], "")` becomes `is_empty`. Its
   hollow-price test becomes `is_substantive` over the composite (`raw` is
   evidence, not data, which is the hasher's rule).
3. The stale docstrings are rewritten (writer step 2, `PriorObservation`, the
   asset-URL test, hashing's table). `PriorObservation.empty_extraction` is
   removed, along with its column in `_LATEST`.
4. `unknown_pages` dedupe: partial unique index `(domain_id, url) WHERE
resolved_at IS NULL` plus `ON CONFLICT DO NOTHING`. Spec 001 §1 is
   updated to match.
5. The quadratic health assessment.
   - A non-empty observation can only lower both ratios.
   - So the writer assesses only when the page is empty, or when the run
     has at most `MINIMUM_PAGES_FOR_A_VERDICT` distinct pages for the domain
     (the minimum gate). That count is a bounded `LIMIT` query.
   - A new `(run_id, page_id)` index on `page_observations` serves both it
     and `_HEALTH`. Neither had an index to use: the only one is
     `(page_id, observed_at)`.
6. Smaller fixes:
   - a. `_TOUCH_PAGE` is `GREATEST`.
   - b. `detect_currency`/`strip_currency` match the longest symbol first
     (`CA$`, `A$`, `NZ$`, `HK$`, `US$` added).
   - c. `FieldRule.fallback` fires when the selector yields no _value_, not
     only when it matches no node.
   - d. Closed by B3.
   - e. `fetch_error` has no producer. Not fixed here; it is a line for
     `1.13`, which is the only code path that sees a fetch fail.

## Files this slice owns

- backend/spydra/adapters/postgres/{observations,tables}.py
- backend/migrations/versions/{8c1d4a9f5e02,156197f778f8}_*.py (frozen view literal only)
- backend/migrations/versions/<new>_page_current_skips_unchanged_*.py
- backend/spydra/extraction/{chain,hashing,transforms}.py
- backend/spydra/extraction/strategies/{selector,structured}.py
- backend/spydra/observations/writer.py
- backend/tests/** (test-writer)
- docs/specs/001-domain-model.md §1, docs/specs/003-extraction.md §4
- bff/src/db/schema/crawl.generated.ts (regenerated, never hand-edited)

## Acceptance

- [ ] B1: a stable page crawled twice reads its full content through
      `page_current`; a changed page reads the new content.
- [ ] B2: no-template pages contribute `(0, 0)` to `pages_crawled` and
      `empty_pages`, and five of them on a first run do not move the domain.
- [ ] B3: an image-only JSON-LD stub plus a working template yields the
      template's fields, through the real chain; a stub alone still yields
      its images; a non-substantive extraction has `content_hash IS NULL`
      and is never `unchanged`.
- [ ] 1: a template with `strip_currency` on the price records the currency.
- [ ] 4: the same empty page on two runs leaves one open `unknown_pages` row;
      after resolving it, a third run opens a new one.
- [ ] 5: assessment still trips on the page that crosses the threshold,
      including the page that brings the run to the minimum.
- [ ] 6a–c each pinned by a test.
- [ ] Migration up/down/up. `make check` green. Mutation: each guard broken
      on purpose goes red.

## Handoff log

- planner: measured B1–B3 (table above), decisions above.

## Open questions — for the human

Carried forward from 1.11/1.12:

1. `strategy` vs `extraction_rung` wants an ADR.
2. Spec 001 §2's diagram lacks the `active → awaiting_approval` edge that
   ADR-0030 needs.
3. Spec 003 §4's "configurable per domain" unchanged policy implies a
   column that does not exist. With B1's view, "skip" is no longer
   equivalent and should probably be struck (see B1).
4. Asset URLs are excluded by value.
5. `MINIMUM_PAGES_FOR_A_VERDICT = 5` is in no spec.
6. The prior lookup is a strict `observed_at <`.
7. Enqueue-by-value picks up non-image URLs.
8. Nothing emits queue depth until 2.8.

New:

9. **B1 vs galleries.** Asset URLs are excluded from the hash, so a product
   whose images were re-uploaded under new URLs writes an `unchanged` row.
   That row's gallery is enqueued and (in 5.2) linked to it, and
   `page_current` no longer returns that row. 5.2 has to resolve this, for
   example by linking to the page's current full row or by treating a
   changed asset set as a change. Phase 1 has no reader of
   `observation_assets`, so nothing breaks now.
10. **B3 picks the first substantive rung, and does not merge rungs.** A stub
    whose images the template does not also select loses them when the
    template wins. Merging rungs would be a spec 003 §1 change.
11. **`unknown_pages` dedupe is a schema decision outside spec 001 §1.**
    I made it (index plus spec edit) rather than leave ~1,700 inbox rows a
    day per large dead-link domain. Revert the migration if you disagree.
