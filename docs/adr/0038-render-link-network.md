# 0038 — The worker reaches the sidecar over a two-member internal network

**Status:** Accepted · 2026-10-22
**Supersedes:** [ADR-0023](0023-render-egress-isolation.md) Decision §1, §2
and §4 (the host-loopback fetch path). ADR-0023 §3 (every inspection port
binds `127.0.0.1`) stands.
**Amends:** [ADR-0036](0036-fixture-site-on-egress-for-the-exit.md) (its
Linux exception is gone), [spec 010](../specs/010-service-topology.md),
[spec 012](../specs/012-render-sidecar.md) §3

## Context

ADR-0023 kept `render` alone on `egress` and had the worker reach it through
the host: `RENDER_BASE_URL=http://host.docker.internal:3001`, with `render`
published on `127.0.0.1:3001`.

- **That path works on Docker Desktop only.** On Linux Docker Engine,
  `host-gateway` is the bridge address, a port bound to `127.0.0.1` refuses
  it, and the worker cannot reach the sidecar. Measured on `develop`:
  `ConnectError [Errno 111] Connection refused`. CI and every Linux host
  are in this position.
- **ADR-0036 papered over it for the exit run.** `docker/compose.linux.yaml`
  added a publish on the bridge address. While that publish was up, a page in
  the browser could reach the sidecar's own API (measured in 1.14's review).

The intent ADR-0023 protects has three parts:

1. a crawled page has no route to `db`, `api` or `bff`;
2. nothing is bound to `0.0.0.0`;
3. the worker can render.

On Linux, it was keeping the first two by failing the third.

## Decision

**A dedicated internal network, `render-link`, whose only members are
`worker` and `render`.** The worker uses `RENDER_BASE_URL=http://render:3001`.

- `render-link` is `internal: true`, so it has no gateway and no way out.
  `render` keeps `egress` as its only way out.
- `render` is still on no network with `db`, `api`, `bff`, `edge` or `web`,
  so none of those names resolve from inside it. Through `render-link` it can
  resolve `worker`, which listens on nothing.
- **There is one compose file for both platforms.** No per-OS override, no
  host hop, and no publish on the bridge address.
  `docker/compose.linux.yaml` is deleted.
- `render` keeps `127.0.0.1:3001` as a **dev inspection port**, like the
  others. It is no longer the fetch path, and a production override strips it
  with the rest (spec 010 §6).

**The sidecar refuses requests that come from a browser.** The browser runs
inside the `render` container, so a page can always reach the sidecar at
`127.0.0.1:3001`, and now at `render:3001` too. Network position cannot
separate the two clients, but request shape can. `render/src/guard.js`
handles this before routing and before the body is read:

- **`403`** for any request that carries `Origin`, `Sec-Fetch-Site`,
  `Sec-Fetch-Dest`, `Sec-Fetch-User` or `Upgrade-Insecure-Requests` (the last
  is on every navigation: without it a page could navigate itself to
  `/healthz` and read the answer, found in review). Chromium sets these, a page can
  neither remove nor forge them, and the worker's httpx client sends none of
  them.
  - `Sec-Fetch-Mode` is deliberately not on the list. Node's own `fetch`
    sends it (measured), and the healthcheck and the acceptance suite are
    Node clients.
- **`415`** for a `POST /render` that is not `content-type: application/json`.
  - This turns away a page's "simple" (`text/plain`, form) POST.
  - **It is not a barrier on its own.** The sidecar intercepts every request
    (`context.route('**/*')`), and under interception Chromium sends a page's
    CORS JSON POST without a preflight. Measured in this slice's tests: with
    the header list emptied and this check kept, a page caused 2 renders.
  - On `render:3001` (plain http, not loopback) Chromium sends no
    `Sec-Fetch-*` headers, so **`Origin` is the check that holds** there.
    Measured: dropping `origin` alone from the list lets a page trigger
    renders.

## Measured (Linux Docker Engine, full stack up, from inside `render`)

| Probe                                                                                                               | Result                                  |
| ------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| DNS `db`, `api`, `bff`, `edge`, `web`, `host.docker.internal`                                                       | `ENOTFOUND`                             |
| DNS `worker`                                                                                                        | resolves (`render-link`)                |
| egress gateway `:5432 :8000 :3000 :8080 :5173 :3001`                                                                | `ECONNREFUSED`                          |
| `worker` on `render-link` (`:22 :80 :3000 :3001 :5432 :8000 :8080 :8099`)                                           | `ECONNREFUSED`                          |
| a page's `fetch` to `api:8000`, `db:5432`, the gateway                                                              | `TypeError` (no route)                  |
| a page POSTing to the sidecar (`render:3001`, `127.0.0.1:3001`; no-cors `text/plain`, CORS JSON, form `text/plain`) | **0 renders**                           |
| the same page against a copy of the sidecar with the guard removed                                                  | **5 renders**: the measurement can fail |
| `make phase1-exit` with no override file                                                                            | green                                   |

## Consequences

- `make up` renders on Linux. CI and the exit run use the same topology as a
  Mac.
- ADR-0036's second exception, and its stated cost, are gone.
- **The api has no path to the sidecar.** Nothing in `spydra/api` calls it
  today. Two things in the specs will need one:
  - spec 010's api `/healthz`, which reports `render`;
  - spec 014's `/inspect`.

  Putting `api` on `render-link` would give a page a route to `api:8000`, so
  that is a phase-3 decision. It is raised in the task file.

- **macOS is not measured, and the likely answer is a hole.** No Docker
  Desktop was in reach. Docker Desktop resolves `host.docker.internal` in
  every container, `render` included, and forwards it to the host's
  loopback. That is exactly the mechanism ADR-0023's own fetch path relied
  on (the worker reaching render's `127.0.0.1:3001`), so a page reaching
  db's `127.0.0.1:5432` or the api's `127.0.0.1:8000` the same way should be
  presumed until measured. This ADR neither opens nor closes it; it states
  it instead of ADR-0023 §3's claim. Measuring it on the Mac, and closing it
  if it holds, is open in `.tasks/fix-2.0-phase1-decisions.md`.
- The guard is a request-shape check, so it is defence of the API surface,
  not of the network. The network boundary is `render-link`'s membership.
  What the guard prevents is a page making the sidecar render on its behalf
  (a context-exhaustion lever).

## Alternatives considered

- **Keep loopback on macOS and add a per-OS override for Linux.** This keeps
  ADR-0036's measured hole in normal `make up` on Linux, and it puts two
  topologies under one test suite.
- **The worker joins `egress`.** The browser could then resolve the worker,
  and `egress` is shared with the exit's `fixtures` service. It is a wider
  membership than `render-link` for no gain.
- **Refuse by source address** (loopback or the container's own IPs). The
  acceptance suite drives the sidecar from inside its own container, so this
  would need an opt-out switch. A guard with an off switch is a gate that
  cannot be trusted to fail.
- **Playwright route interception.** ADR-0023 rejected it as defence in depth
  only, and it does not cover WebSockets or service workers.
