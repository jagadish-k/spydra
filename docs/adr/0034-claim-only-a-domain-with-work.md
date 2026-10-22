# 0034 — The claim takes only a domain with work, for the pool that asks

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0026](0026-claim-locks-the-domain-row.md),
[spec 002](../specs/002-scheduler.md) §1 and §6

## Context

ADR-0026's claim locks the single most eligible `active` domain and then
takes a pending row _of that domain_. "Most eligible" is the smallest
`next_eligible_at`, and the CTE never asked whether the domain had anything
to fetch.

A domain whose queue has drained is never fetched again. Its
`next_eligible_at` never advances, so it stays the most eligible domain for
good, the CTE locks it on every claim, finds no row, and returns nothing.
Every other domain in the run then waits for ever. BUILD_PLAN `1.12`
observed this as "three `None` claims in the backpressure test" and named it
for `1.13`. Building `1.13`'s loop showed it is permanent, not occasional:
the first domain to finish its queue stops the crawl.

Separately, spec 002 §6 gives rendered domains their own pool, sized to the
sidecar. A claim that ignored `render_mode` let a static-pool loop take a
rendered domain's row, and let a rendered-pool loop spend a sidecar-sized
slot on a static page.

## Decision

Two predicates inside the `eligible` CTE, beside the existing ones:

```sql
AND d.render_mode = ANY(:render_modes)
AND EXISTS (SELECT 1 FROM crawl.crawl_queue q0
            WHERE q0.domain_id = d.id AND q0.state = 'pending')
```

`render_modes` is the claiming pool's set: `{static, auto}` for the static
pool and `{rendered}` for the rendered pool. An AUTO domain's second chance
is issued from the static pool, so the sidecar budget is a semaphore around
the rendered fetcher that both pools share, not a pool size.

**Both of ADR-0026's locks are unchanged.** The `EXISTS` reads without a
lock; if the only pending row is taken between the check and the inner
`SKIP LOCKED`, that claim returns `None` and the loop goes round, which is
the ordinary case the loop already handles.

## Consequences

- One domain finishing no longer stops the others. A test asserts it against
  two domains, one of them drained.
- The `EXISTS` is served by `ix_crawl_queue_domain_pending`.
- A `None` claim still never means "the frontier is empty"; the worker idles
  and goes round until it is stopped.
