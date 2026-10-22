# ADR-0023 — The render sidecar is reached through the host, not a shared network

**Status:** Accepted · 2026-10-15
**Amended by:** [ADR-0036](0036-fixture-site-on-egress-for-the-exit.md) (a test-only fixture service, behind a profile)
**Context:** phase 0 · affects `docs/specs/010-service-topology.md`,
`docs/specs/012-render-sidecar.md`, `docs/DEVELOPMENT.md`, `compose.yaml`

---

## Context

Spec 012 §3 requires network isolation for the render sidecar: it fetches
arbitrary operator-supplied URLs with a real browser, so a crawled page must
not be able to reach `http://db:5432` or `http://api:8000` — "no route
inward … the only real isolation boundary in the stack".

The compose sketch in `DEVELOPMENT.md` puts `render` on the `egress` network
**alone** (every other service is on `default`). Docker bridge networks are
symmetric: services can reach each other iff they share a network. That
sketch is therefore internally inconsistent —

- as drawn, nothing can call `render:3001`, yet `RenderServiceFetcher`
  (spec 012 §4) must;
- the "obvious" fix — attaching `api`/`worker` to `egress` too — shares a
  network between the browser and the API, so a crawled page resolves and
  reaches `http://api:8000` and the spec 012 §6 acceptance ("a page fetching
  `http://api:8000/…` cannot reach it") fails by construction.

Asymmetric reachability (api → render but not render → api) is not
expressible with plain compose networking.

## Decision

**`render` stays on `egress` alone, and `api`/`worker` reach it through the
host loopback, not through a shared docker network.**

1. `render` publishes `127.0.0.1:3001:3001` and joins only `egress`. From
   inside `render`, no internal service name resolves — not `db`, not `api`,
   not `bff`. That is the isolation the spec asks for.
2. `RENDER_BASE_URL=http://host.docker.internal:3001`. The `api` and
   `worker` services already carry `extra_hosts:
["host.docker.internal:host-gateway"]` (added for `llama-server`,
   ADR-0009), so this resolves on every platform this project runs on —
   Docker Desktop on macOS is both the dev and the target environment.
3. **Every dev inspection port is bound to `127.0.0.1`** —
   `127.0.0.1:5432:5432`, `127.0.0.1:8000:8000`, `127.0.0.1:3000:3000`,
   `127.0.0.1:5173:5173`, and `render`'s loopback publish above. On Docker
   Desktop, containers can resolve `host.docker.internal` by default, so a
   crawled page could otherwise probe the host's published ports via the
   gateway IP. Loopback-only binding means the gateway probe is refused:
   the page has no name that resolves and no IP that answers. This binding
   is part of the security boundary, not a style choice — a port rebound to
   `0.0.0.0` reopens the boundary and is a defect.
4. The loopback publish on `render` is **not** a dev-only convenience (unlike
   the other inspection ports): it is the fetch path. It stays in every
   environment; the other publishes are stripped in a prod override
   (spec 010 §6, "only `edge` publishes in production" — `render`'s
   loopback bind publishes to the host's loopback, not to the network).

## Consequences

- Spec 012's isolation acceptance passes **literally**: from inside the
  browser, neither `http://api:8000` (no shared network, no DNS) nor
  `http://host.docker.internal:8000` (gateway IP, nothing bound there)
  reaches anything.
- `api`/`worker` → `render` traffic makes one loop through the host. Against
  a 2–5 s render this is unmeasurable.
- The fetch path depends on `render` publishing its port — a coupling worth
  one comment in `compose.yaml`, which this ADR is the reason for.
- If the sidecar is ever replaced by a hosted renderer (ADR-0016), the
  indirection disappears entirely: `RENDER_BASE_URL` points at the real host
  and the loopback publish is deleted.

## Alternatives rejected

| Option                                                    | Why not                                                                                                                                           |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api`/`worker` join `egress` with `render`                | Shares a network between the browser and the API; the page reaches `http://api:8000` and spec 012 §6 fails by construction                        |
| A tiny forwarding proxy on both networks                  | A seventh service whose only job is to not be Caddy; and if the edge does it, the page can reach the edge and everything behind it                |
| Playwright route interception blocking internal hostnames | Defense in depth at best — the page's `fetch()` still resolves DNS and connects at the OS level; the spec asks for the network to be the boundary |
| Firewall rules inside the `render` container              | Not expressible in plain compose; a second mechanism to maintain and test                                                                         |
