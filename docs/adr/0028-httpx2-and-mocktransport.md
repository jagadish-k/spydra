# 0028 — httpx2 for the Fetcher, and its own MockTransport instead of respx

**Status:** Accepted · 2026-10-18
**Amends:** [`AGENTS.md`](../../AGENTS.md) § Stack,
[`TESTING.md`](../TESTING.md) §1
**Relates to:** [ADR-0008](0008-ports-and-adapters.md) (the `Fetcher` port),
[ADR-0016](0016-render-sidecar.md) (the second adapter),
[ADR-0017](0017-version-policy.md) (track latest, behind a readiness gate)

## Context

`AGENTS.md` § Stack names **httpx** as the backend HTTP client and
`TESTING.md` §1 names **respx** to mock it. `BUILD_PLAN` 1.6 builds
`HttpxFetcher` against both.

Two things made that untenable before 1.7 was written:

- Starlette 1.8's `TestClient` emits a deprecation warning on httpx and asks
  for **httpx2** by name. httpx2 2.13.1 (23 Sep 2026) is the continuation
  Pydantic maintains; httpx's own successor page describes httpx as seeing
  limited recent activity. The test-client dependency was already swapped for
  that reason, which left the repository naming two different HTTP clients in
  two different documents.
- **respx cannot follow.** 0.23.1 (Apr 2026) requires `httpx>=0.25`, has no
  httpx2 support, and its classifiers stop at Python 3.14 against this
  project's 3.15 — so ADR-0017's readiness gate fails on it twice over.

So the question is not "httpx or httpx2" — that was settled by the client's
own maintenance story. It is what replaces respx.

## Decision

**httpx2 is the Fetcher's HTTP client, and `httpx2.MockTransport` is how it
is tested. respx is removed and nothing replaces it as a dependency.**

```python
def handler(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/robots.txt":
        return httpx2.Response(200, text="User-agent: *\nCrawl-delay: 10\n")
    if request.url.path == "/blocked":
        return httpx2.Response(403)
    return httpx2.Response(200, html="<h1>ok</h1>")

async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
    ...
```

Verified against httpx2 2.13.1 before this was written: `MockTransport`
accepts a sync or async handler, drives the full status table 1.7 and 1.8
need (200, 403, 429, 503, 5xx), passes request headers through so the
user-agent assertion from ADR-0004 is testable, and handles redirects.

Three reasons it beats a mocking library here:

1. **It is zero new dependencies.** `AGENTS.md` forbids a new runtime
   dependency without an ADR, and the best answer to a dependency question is
   usually not a different dependency. respx was convenience, never
   capability.
2. **It intercepts at the transport, which is the seam ADR-0008 already
   chose.** The `Fetcher` port is the only place the crawler touches HTTP, so
   there is exactly one thing to substitute. respx patches the library
   globally — a bigger hammer than a codebase with one HTTP boundary needs.
3. **It cannot fall behind the client.** `MockTransport` ships _in_ httpx2,
   so a client upgrade can never leave the mocking layer stranded on an old
   version — which is precisely how respx became unusable here.

`TESTING.md` §1's rule is unchanged and is the point: **no network in unit
tests.** Only the mechanism changes.

## Consequences

- **`TESTING.md` §1 and `AGENTS.md` § Stack now agree**, and both say httpx2.
  They have disagreed since the test-client swap.
- **`respx` never entered the lockfile**, so there is nothing to remove from
  `backend/uv.lock` — only two documents that named it. It was specified and
  never installed, which is its own small lesson about documents that
  describe intentions rather than state.
- **1.7's tests are plain pytest** with a handler function per scenario, and
  `RenderServiceFetcher` (1.7) is tested the same way against the sidecar's
  HTTP contract. One pattern for both adapters, which is what ADR-0008 wanted
  from the port in the first place.
- **Cost: handler functions are more verbose than respx's route matchers.** A
  respx test reads `respx.get("...").mock(return_value=...)`; this reads as a
  small dispatch function. For a handful of fetcher tests that is a fair
  trade for no dependency and no version coupling; if the fetcher suite ever
  grows to dozens of URL patterns, a shared handler factory in a fixture is
  the answer rather than a library.
- **Cost: no assertion helpers.** respx records calls and offers
  `assert_all_called`. Here a test that wants to assert on what was requested
  collects requests in the handler's closure. Three lines, and it keeps the
  assertion visible in the test rather than in a plugin's state.

## Alternatives considered

**Keep respx and pin httpx for the Fetcher**, letting the test client use
httpx2. Rejected: two HTTP clients in one service, with the real crawl path on
the one whose maintenance is winding down and whose successor the test client
already demands. ADR-0017 exists to stop exactly this.

**`pytest-httpx`.** Rejected without much hesitation: it is another plugin
coupled to a specific client major, which is the failure mode respx just
demonstrated. If `MockTransport` ever proves insufficient this is where to
look again — but it has to earn the dependency.

**A local HTTP server serving fixtures.** Rejected for unit tests: real
sockets, real ports, real flakiness, and it tests the server as much as the
fetcher. It is the right shape for the Playwright suite (`TESTING.md` §1
already says so) and the wrong shape here.

**Keep respx and drop to Python 3.14.** Rejected. Moving the whole project's
interpreter to accommodate one test-only library inverts ADR-0017's
readiness gate.
