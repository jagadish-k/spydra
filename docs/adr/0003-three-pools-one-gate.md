# 0003 — Three worker pools behind one per-domain gate

**Status:** Accepted · 2026-10-15 · rendered pool amended by [ADR-0016](0016-render-sidecar.md)

> The three-pool model and the per-domain gate stand. Only the *rendered*
> pool changed: browser contexts moved out of the worker into a sidecar.
> A rendered fetch still claims the same per-domain lock.

## Context

Politeness is a per-host constraint, so concurrency *within* a host is what
risks a block. But treating every request identically — HTML and images alike
— makes the crawler far slower than it needs to be, because images are
typically 70–80% of the bytes and a single product page yields several.

A product page and a product image are not the same kind of request. A page is
dynamic: it hits application code, touches a database, costs the origin real
CPU, and appears in their logs as a crawl pattern. An image is a static byte
range, usually served from cache or a CDN edge, costing the origin almost
nothing. Six concurrent image fetches is ordinary browser behaviour — a real
browser opens about that many connections per host to render one page.

Rendered pages are a third case: a Playwright context costs roughly 300 MB and
2–5 s per page, so it cannot share the static pool's sizing.

## Decision

Three pools in one worker process, as three `asyncio` loops over one
connection pool:

| Pool | Workers | Per-host limit | Gate |
| --- | --- | --- | --- |
| Static pages | 8–16 | 1 concurrent, 2 s gap | `domains.next_eligible_at` in Postgres |
| Rendered pages | 3 contexts | 1 concurrent, same gate | same |
| Assets | 16–32 | 4–6 concurrent, 200 ms gap | in-process semaphore per host |

A rendered fetch claims the **same** per-domain lock as a static one, so a
domain is fetched one page at a time whichever adapter serves it. Only pool
sizing differs.

Assets are **enqueued, not fetched inline**: a page worker extracts image
URLs, inserts `asset_queue` rows and moves on. It never blocks on an image.

Page politeness lives in Postgres because the limit must hold across worker
replicas and restarts. Asset concurrency is an in-process semaphore because a
loose limit is a throughput knob, not a correctness property.

## Consequences

- The resulting traffic shape — one page every two seconds plus bursty asset
  fetches from a CDN — looks like a visitor. Sequential everything looks like
  a crawler.
- An image host being slow or down does not affect the page crawl rate, and
  the asset pool keeps draining after page crawling for a domain finishes.
- **Backpressure is required.** If `asset_queue` exceeds 10,000 pending rows,
  page workers slow down. Without it, a fast crawl over an image-heavy
  catalogue builds a queue that outlives the run by hours.
- **Cost:** three pools is more moving parts than one, and the split brain
  between a database-enforced limit and an in-process one is a real
  inconsistency. Two workers each allow 5 concurrent asset fetches per host,
  so the true limit is 10. That is accepted deliberately: for assets the limit
  is a tuning knob, and the simplicity of not round-tripping to Postgres for
  every image is worth more than the precision.

## Alternatives considered

**One pool, one limit.** Rejected: throughput becomes unusable (with 2–3
domains active during onboarding you would see 2–3 concurrent fetches total,
including images) and it does not reduce block risk, because the risk comes
from page requests, not image requests.

**Asset concurrency enforced in Postgres too.** Rejected: a database
round-trip per image, for a limit that does not need to be exact.
