# 0039 — A listing template's page is never an empty extraction verdict

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0027](0027-no-required-fields.md) §3 (who is inside the
threshold), [ADR-0030](0030-empty-needs-a-prior.md) (its denominator)

## Context

Phase 2 crawls from category seeds. A category or listing page is matched by
a template whose `page_kind` is `listing`: it carries discovery rules
(spec 004 §1) and, normally, no extraction fields, because nothing on it is
product data.

ADR-0027 §3 keeps pages with **no** template out of the `broken` threshold,
and out of the `empty_extraction` inbox reason. It says nothing about
listing templates, and the code treated any page with a template as an
extraction. So every listing page came back as an empty extraction: an inbox
row each, and, on a first run where listings are more than 20% of pages,
`NEVER_MATCHED` moved a healthy domain to `awaiting_approval`. Found building
2.3, before any domain was crawled from a category.

## Decision

**Only a page matched by a `product` template is inside the extraction
verdict.** A `listing` page's observation is still written (append-only,
fields if the template has any), but:

- it never gets the `empty_extraction` inbox reason;
- it is not in ADR-0030's numerator or denominator, nor the minimum-sample
  count.

The reason is ADR-0027 §3's, extended: an empty listing page says nothing
about whether product extraction works, so counting it either dilutes a real
redesign or invents one.

## Consequences

- A category crawl's listings no longer halt the domain or fill the inbox.
- **Cost: a listing redesign is not caught by this detector.** If listing
  selectors stop matching, discovery finds nothing and the run simply
  crawls fewer pages. That failure is visible as a drop in discovered and
  crawled counts per run (`runs.stats`, 2.7), not as `broken`. A per-rule
  discovery count in the run report (2.7, 2.10) is the place to make it loud.
- `runs.stats.empty_extractions` still counts listing rows whose fields are
  empty; it is a raw count, not the verdict.

## Alternatives considered

- **Give listing templates a dummy field** (the category name) so they are
  never empty. That makes the threshold measure category headings, and a
  redesign that keeps the heading would read as healthy.
- **Exclude by URL pattern or by "has discovery rules".** `page_kind` is the
  field spec 001 §1 already defines for exactly this distinction.
