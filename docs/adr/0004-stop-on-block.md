# 0004 — A block stops the crawler; it is never retried through

**Status:** Accepted · 2026-10-15

## Context

The operator named being blocked as the worst outcome. Standard HTTP client
behaviour — retry with backoff — is exactly wrong against a block: a site that
has decided to refuse you interprets continued requests as confirmation that
you are a bot, and a temporary rate-limit becomes a permanent IP ban.

## Decision

- **429 or 503** → exponential backoff on that domain (×2, capped at 15
  minutes), `consecutive_failures` incremented. The domain stays active.
- **Three consecutive 403s** → the domain is auto-paused, crawling stops
  mid-run, and it is surfaced in the UI as requiring attention.
- The crawler identifies itself honestly: a descriptive User-Agent with
  contact information. It does not impersonate Chrome.
- `robots.txt` is fetched once per domain per run. A `Crawl-delay` directive
  **raises** the configured delay if it is higher and never lowers it.

Proxy rotation is explicitly out of scope. If it is ever needed, the
polite-crawling assumptions have already failed and need revisiting, not
patching.

## Consequences

- A blocked domain yields partial data for that run and needs human attention
  before it resumes. That is the intended outcome.
- Run completion is not guaranteed. The UI must show abandoned work honestly
  rather than reporting a clean finish.
- **Cost:** a transient 403 — a WAF hiccup, a bad edge node — pauses a domain
  that would have recovered on its own, and the operator has to resume it by
  hand. Accepted: the cost of a needless pause is minutes of attention; the
  cost of a permanent ban is the domain.
