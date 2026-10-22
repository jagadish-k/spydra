# 0036 — A test-only fixture service may join `egress`, behind a profile

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0023](0023-render-egress-isolation.md) (render is alone on
`egress`), for one test profile only
**Amended by:** [ADR-0038](0038-render-link-network.md): the Linux exception
below is withdrawn; the worker reaches `render` over `render-link` everywhere

## Context

Phase 1's exit criterion crawls the local fixture site end to end, through
**both** fetchers in the same scheduler: a static page via the worker, and a
JavaScript-dependent page via the render sidecar.

ADR-0023 puts `render` alone on the `egress` network, so that a page loaded in
the browser has no internal name to resolve. The worker is on `default`. No
fixture site can be seen by both:

- The render suite runs 1.4's `server.py` on the sidecar's own loopback, which
  the worker cannot reach.
- The Python suite runs it on the api container's loopback, which the sidecar
  cannot reach, by design.

## Decision

A **`fixtures`** service runs 1.4's own `server.py` (one route table, not a
copy):

- It joins **both** `default` and `egress`.
- It sits behind a compose **profile** (`phase1-exit`). `make up` never starts
  it, and nothing in a normal stack can see it.
- It binds no host port.

The exit run is `make phase1-exit`, which brings the profile up, runs the
check and takes it down.

**A second, Linux-only exception** (`docker/compose.linux.yaml`) was
withdrawn by ADR-0038, which gives the worker a route to the sidecar that works
on every platform. The file is deleted.

## Consequences

- With the profile up, a page in the browser can resolve four more names
  (`fixtures` and the three fixture-domain aliases). They serve hand-written
  static HTML and 1.4/1.5's generated test routes, and nothing else. None is a
  route to `db`, `api` or `bff`, which are still not on `egress`.
- Without the profile, the topology is exactly ADR-0038's on every platform.

## Alternatives considered

- **Run the whole exit inside the render container.** That cannot exercise
  the worker, which is half of what the criterion is about.
- **Publish the fixture site on the host, reached through
  `host.docker.internal`.** That needs `extra_hosts` on `render`, which
  ADR-0023 forbids outright. It would also make the host's loopback
  reachable from inside the browser, which is the boundary ADR-0023 draws.
