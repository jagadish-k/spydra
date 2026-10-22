# 0033 — Current state skips lightweight rows; "nothing comparable" has no hash

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0007](0007-append-only-observations.md) (the `page_current`
definition), [spec 001](../specs/001-domain-model.md) §1,
[spec 003](../specs/003-extraction.md) §4
**Relates to:** [ADR-0027](0027-no-required-fields.md),
[ADR-0030](0030-empty-needs-a-prior.md)

## Context

ADR-0007 defines current state as the newest observation of each page, and
its first guard writes a **lightweight row** (`unchanged = true`, no fields)
when the content hash matches the previous one. BUILD_PLAN `1.11` built both
literally. They contradict each other: from a page's second run, the newest
observation of every stable page is a row with no fields, so the one
sanctioned reader of current state said every unchanged product had no title
and no price. This was measured on real Postgres, not inferred.

A second gap sat beside it. The hash is taken over the normalised fields,
and normalisation excludes asset URLs (spec 003 §4). So a page from which
nothing resolved and a page whose only field is an image URL both
normalised to `{}` and shared one hash. The writer read that equality as
`unchanged`, and recorded "nothing to compare" as "the same as before" for
ever.

## Decision

1. **`page_current` skips `unchanged` rows:**

   ```sql
   SELECT DISTINCT ON (page_id) * FROM page_observations
   WHERE NOT unchanged ORDER BY page_id, observed_at DESC
   ```

   An `unchanged` row asserts "same content as the row before", so the newest
   row that is not `unchanged` _is_ the current content. When the page was
   last seen is `pages.last_crawled_at`, which is monotonic.

2. **When nothing survives normalisation there is no hash.**
   `content_hash` is NULL, and a row with a NULL hash is never `unchanged`.
3. **Read-time diffs skip `unchanged` rows too.** ADR-0007's `price_history`
   ("observations where `price_amount` differs from the prior row") compares
   against the prior **full** row. A naive comparison with the previous row
   reads every stable run as price → NULL → price.

## Consequences

- Current state and the lightweight row are compatible, and ADR-0007's
  storage saving stands.
- `page_current.observed_at` is when the content was last _different_, not
  when it was last _seen_. A reader that wants recency joins `pages`.
- **Spec 003 §4's "skip and bump `last_crawled_at`" stops being equivalent.**
  ADR-0030's denominator is the pages observed in this run, so a skipped
  stable page leaves it, and three regressions among thousands of stable
  pages would read as 100%. That branch should be struck rather than built;
  it is raised in `.tasks/fix-1.11-review-findings.md`.
- **Galleries.** Asset URLs are not hashed, so a re-uploaded gallery on an
  otherwise stable page writes an `unchanged` row, and its assets are
  enqueued against a row the view does not return. Reconciling the two
  belongs to `5.2`, which is the first reader of `observation_assets`.

## Alternatives considered

**Repeat the fields on an unchanged row.** Rejected: it contradicts the
lightweight row ADR-0007 chose, and it stores every stable catalogue again on
every run.

**Skip the write entirely.** Rejected for the denominator reason above, and
because `asset_queue` rows have to hang off an observation.
