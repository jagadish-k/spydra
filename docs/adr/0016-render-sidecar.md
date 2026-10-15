# 0016 — Headless rendering runs in a sidecar

**Status:** Accepted · 2026-10-15
**Relates to:** ADR-0003 (the rendered pool), ADR-0008 (the `Fetcher` port)

## Context

The obvious place for the browser is the worker process, as a third pool of
contexts alongside the static and asset pools. That works, and it carries
three costs that only become obvious once the image is built:

1. **Image size.** Playwright plus Chromium plus its system libraries takes
   the worker image past 1.5 GB. The actual crawler is a few megabytes of
   Python.
2. **Blast radius.** A Chromium OOM or a hung context takes down the process
   that is also running the static page pool and the asset pool.
3. **Coupled scaling.** Browser memory and crawl concurrency have nothing to
   do with each other, but one process means one scaling knob.

## Decision

Rendering moves to a **stateless sidecar**: a small Node service wrapping
Playwright, exposing an HTTP contract.

```
POST /render
  { "url": "...", "wait_until": "networkidle", "timeout_ms": 20000,
    "block_resources": ["image", "font", "media"] }
→ { "html": "...", "status": 200, "final_url": "...",
    "timing_ms": {"navigate": 1840, "total": 2210} }

GET /healthz   → { "ok": true, "contexts_in_use": 2, "contexts_max": 3 }
```

The Python side keeps the `Fetcher` port from ADR-0008. `PlaywrightFetcher`
becomes **`RenderServiceFetcher`**, an HTTP client. The scheduler is
unchanged: a rendered fetch still claims the same per-domain lock as a static
one (ADR-0003 §gate survives intact).

**Node, not Python**, for the sidecar: Playwright's Node API is the reference
implementation and the official `mcr.microsoft.com/playwright` Node image is
the canonical pairing of library and browser build. Pin the package to the
same version as the image tag or the driver and browser mismatch.

Context pooling, recycling every 50 pages, and the hard cap of 3 concurrent
contexts move **into the sidecar**, where they belong — they are properties
of the browser, not of the crawl.

## Consequences

- **The worker image loses Chromium.** It drops from ~1.5 GB to roughly
  200 MB, and the Python app no longer depends on the `playwright` package at
  all — which also removes one of the slower packages to support a new Python
  release (ADR-0017).
- A browser crash returns a 5xx to one fetch instead of killing the worker.
- Render capacity scales by replica, independently of crawl concurrency. A
  JS-heavy onboarding week means more render replicas, not more workers.
- The contract is language-agnostic, so the sidecar could be replaced by
  browserless or a hosted renderer without touching Python.
- **Cost:** an HTTP hop and a serialisation of the full page HTML on every
  rendered fetch — tens of milliseconds and a few hundred KB against a 2–5 s
  render, so immaterial. The real cost is one more service to run, one more
  health check to watch, and a new failure mode: the sidecar being unreachable
  while the crawl is otherwise healthy. Treat it like `llama-server` — a
  declared dependency whose absence degrades a path rather than the system.

## Behaviour when the sidecar is down

A domain with `render_mode = rendered` cannot be crawled; its queue rows stay
`pending` and the run reports them honestly rather than marking them failed.
A domain with `render_mode = auto` falls back to the static result and records
`strategy = static_fallback`, so the operator can see which pages were
collected without rendering. Static domains are unaffected.
