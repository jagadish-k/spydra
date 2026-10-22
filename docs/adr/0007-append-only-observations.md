# 0007 — Observations are append-only; current state is a view

**Status:** Accepted · 2026-10-15

## Context

The operator asked for change tracking: prices and availability move, and the
point of re-crawling is to see that. The naive implementation updates a
`products` row in place and keeps an `updated_at`. That records _when_ you
looked, not _what changed_, and the difference cannot be retrofitted — once a
value is overwritten the history is gone.

## Decision

Every crawl writes a `page_observations` row. Nothing is ever updated in
place. Current state is the `page_current` view
(`DISTINCT ON (page_id) … ORDER BY page_id, observed_at DESC`), **which skips
`unchanged` rows**: [ADR-0033](0033-current-state-skips-lightweight-rows.md).

Two guards keep the table from filling with identical rows:

1. **`content_hash`** over the _normalised extracted fields_ — not the raw
   HTML, which changes on every request because of timestamps and session
   tokens. If the hash matches the previous observation, write a lightweight
   row (timestamp, status, `unchanged` flag) or skip and bump
   `pages.last_crawled_at`, configurable per domain.
2. **Field-level diffing is computed at read time, not stored.** A
   `price_history` view over observations where `price_amount` differs from
   the prior row gives the change series without a second table.

Observations are kept indefinitely — they are small and they are the point of
the system. Only `raw_html_path` files are purged, on a 7-day TTL, by a sweep
at the start of each run.

## Consequences

- Price history, field diffs and "disappeared products" are all queries over
  one table rather than features needing their own storage.
- A silently broken selector is visible as a step change in the series rather
  than as quietly overwritten data.
- **Cost:** the table grows without bound, and `page_current` is a
  `DISTINCT ON` over it, which will need an index and eventually may need a
  materialised view. At the expected volume (tens of thousands of pages,
  infrequent runs) this is years away, but it is the thing that will need
  attention first.
