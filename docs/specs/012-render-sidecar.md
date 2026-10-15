# 012 — Render sidecar

**Phase 1** (+ `/inspect` in phase 6) · Node + Playwright · ADR-0016

A stateless HTTP service wrapping Playwright. The Python side keeps the
`Fetcher` port and talks to it over HTTP; it has no browser dependency at
all.

> The official `mcr.microsoft.com/playwright` image decides the sidecar's
> Node major (v1.64.1-noble ships Node 24, not the repo's Node 26). That is
> accepted: the npm-package↔image-tag pairing is what is load-bearing
> (ADR-0016), and the Node-26 policy governs the images _we_ pick the base
> for (`bff`, `web` — ADR-0017).

---

## 1. Contract

```
POST /render
{
  "url": "https://example.com/products/x",
  "wait_until": "networkidle",         // load | domcontentloaded | networkidle
  "wait_for_selector": ".price",       // optional, takes precedence
  "timeout_ms": 20000,
  "block_resources": ["image", "font", "media"],
  "user_agent": "Spydra/1.0 (+mailto:…)",
  "extra_headers": {}
}
→ 200
{
  "html": "<!doctype html>…",
  "status": 200,
  "final_url": "https://example.com/products/x",
  "timing_ms": {"navigate": 1840, "settle": 370, "total": 2210},
  "console_errors": 0
}
```

| Code | Meaning                                           | Python side                  |
| ---- | ------------------------------------------------- | ---------------------------- |
| 200  | Rendered                                          | proceed to extraction        |
| 422  | Bad request (malformed URL, unknown `wait_until`) | bug; fail the page           |
| 502  | Navigation failed (DNS, connection refused)       | treat as a fetch error       |
| 504  | Render timed out                                  | retry once, then fetch error |
| 503  | No context available within the queue timeout     | backpressure; retry later    |

```
POST /inspect → screenshot + element geometry + skeleton, for the visual
playground. **Specified in [spec 014](014-playground.md) §2**, not here: the
contract belongs with the screen that consumes it. What belongs here is that
it shares this service's browser, context cap, recycling policy and network
isolation — it is another route, not another service. It counts against the
same three contexts, so an authoring session and a rendered crawl compete;
that is correct, since both are real browser work on one machine.
```

```
GET /healthz → {"ok": true, "contexts_in_use": 2, "contexts_max": 3,
                "pages_since_restart": 1204, "browser_version": "…"}
```

**The sidecar does not retry and does not back off.** It renders one page or
fails. Politeness, retries and backoff are the scheduler's job (spec 002),
and duplicating them here would mean two components with opinions about the
same thing.

## 2. Browser management

- **One browser instance**, N contexts. A context per request, closed after.
  Contexts are cheap; browsers are not.
- **Hard cap of 3 concurrent contexts** (`RENDER_CONTEXTS`). Requests beyond
  it queue for up to 5 s, then 503.
- **Recycle the browser every 500 pages or 30 minutes**, whichever first.
  Chromium leaks under sustained automation; a scheduled restart is cheaper
  than diagnosing it. Drain in-flight contexts before restarting.
- **Block `image`, `font`, `media` by default** via route interception. The
  asset pool downloads images separately (spec 008), so rendering them is
  pure waste — it typically halves render time.
- `--disable-dev-shm-usage` and a `/dev/shm` size of at least 1 GB in compose.
  The default 64 MB makes Chromium crash in ways that look like random
  timeouts.

## 3. Safety

This service fetches arbitrary operator-supplied URLs with a real browser. It
is the largest attack surface in the system even though it only ever serves
one user.

| Guard              | Setting                                            |
| ------------------ | -------------------------------------------------- |
| Request body       | 64 KB max                                          |
| Response HTML      | 10 MB max; truncate and flag beyond                |
| Navigation timeout | 30 s hard ceiling regardless of request            |
| JavaScript dialogs | auto-dismissed; never block                        |
| Downloads          | disabled                                           |
| Permissions        | geolocation, camera, mic, notifications all denied |
| Network            | **no access to the docker-internal network**       |

The last one matters. Put `render` on an egress-only network with no route to
`db`, `api` or `bff`. A page that fetches `http://db:5432` or
`http://api:8000/api/crawler/domains` should not be able to reach anything.
This is cheap to configure and the only real isolation boundary in the stack.

## 4. The Python side

`RenderServiceFetcher` implements `Fetcher` (ADR-0008) and is selected by
`domains.render_mode`:

| Mode       | Behaviour                                                                                                                              |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `static`   | `HttpxFetcher` only                                                                                                                    |
| `rendered` | `RenderServiceFetcher` only                                                                                                            |
| `auto`     | static first; if the template's **required** fields fail to resolve on a 200, retry once through the sidecar and record which path won |

`auto` is why the cost of a wrong onboarding guess is one wasted cheap fetch
rather than a silently empty extraction. After a few runs the flag can be
pinned from observed behaviour.

**The per-domain politeness gate is unchanged.** A rendered fetch claims the
same lock as a static one (ADR-0003); only pool sizing differs.

**Sidecar unavailable:** `rendered` domains leave their queue rows `pending`
and the run reports them as stalled, not failed. `auto` domains fall back to
static and record `strategy = static_fallback`. `static` domains are
unaffected.

## 5. Why Node

Playwright's Node API is the reference implementation and the official
`mcr.microsoft.com/playwright` Node image is the canonical pairing of library
and browser build. **Pin the npm package to the same version as the image
tag** — a mismatch between driver and browser produces errors that read like
page faults.

## 6. Acceptance

- [ ] A JS-rendered fixture returns HTML containing content absent from the
      raw response.
- [ ] A fourth concurrent request queues and then 503s rather than opening a
      fourth context.
- [ ] `block_resources` measurably reduces render time on an image-heavy page.
- [ ] A page opening `alert()` does not hang the request.
- [ ] A page fetching `http://api:8000/…` cannot reach it (network isolation).
- [ ] The browser restarts after the page threshold without dropping an
      in-flight render.
- [ ] A 20 MB HTML response is truncated and flagged, not streamed whole.
- [ ] With `render` stopped: `static` domains crawl, `auto` falls back and
      records it, `rendered` stalls honestly.
- [ ] The Python image contains no `playwright` package and no browser.
- [ ] `/inspect` and `/render` share the context cap: three renders in flight
      make an `/inspect` call queue, not open a fourth context.
