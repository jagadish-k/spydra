# 0036 — A test-only fixture service may join `egress`, behind a profile

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0023](0023-render-egress-isolation.md) (render is alone on
`egress`), for one test profile only

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

**A second, Linux-only exception** (`docker/compose.linux.yaml`). ADR-0023's
worker-to-sidecar path, a host-loopback publish reached via
`host.docker.internal`, works only on Docker Desktop. On Linux Docker Engine
(CI runners, cloud containers) `host-gateway` is the docker0 bridge address,
a port bound to 127.0.0.1 refuses it, and the worker cannot reach the sidecar
at all (measured: connection refused). For the exit run only, the override
adds a publish on the bridge address. `scripts/phase1-exit.sh` recreates
render from `compose.yaml` alone when it finishes, so the publish does not
outlive the run.

## Consequences

- With the profile up, a page in the browser can resolve four more names
  (`fixtures` and the three fixture-domain aliases). They serve hand-written
  static HTML and 1.4/1.5's generated test routes, and nothing else. None is a
  route to `db`, `api` or `bff`, which are still not on `egress`.
- **On Linux, during the exit run, a page in the browser can reach the
  sidecar's own API** at the bridge address (measured in review), and so
  could ask it to render other URLs. The pages it loads are the fixtures,
  which are ours. This is the cost of exercising both fetchers on Linux at
  all, and it lasts for one script's duration.
- Without the profile, and outside the exit script, the topology is exactly
  ADR-0023's on every platform.
- **ADR-0023 has no answer for a Linux deployment.** Its fetch path does not
  work on Linux Docker Engine. This ADR only makes the exit runnable; the
  deployment question is open and raised in `.tasks/feat-1.14-yaml-loader.md`.

## Alternatives considered

- **Run the whole exit inside the render container.** That cannot exercise
  the worker, which is half of what the criterion is about.
- **Publish the fixture site on the host, reached through
  `host.docker.internal`.** That needs `extra_hosts` on `render`, which
  ADR-0023 forbids outright. It would also make the host's loopback
  reachable from inside the browser, which is the boundary ADR-0023 draws.
