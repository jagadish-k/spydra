# 0015 — Service topology: edge, BFF, API, worker, render sidecar

**Status:** Accepted · 2026-10-15

## Context

The original design was one Python application (API + worker) plus a Vite
dev server. The operator wants the work separated: UI concerns and scheduling
in a Node BFF, crawling and parsing in Python, headless rendering offloaded
entirely, and a gateway in front.

The risk in any such split is building a **distributed monolith** — services
that are separate processes but share tables, so every change touches two
repositories and every request makes a network hop for no isolation benefit.
Avoiding that is entirely about where the data boundary sits, not about how
many containers there are.

## Decision

Six services, with one rule: **a service owns its data and nobody else
writes it.**

| Service | Runtime | Owns | Talks to |
| --- | --- | --- | --- |
| `edge` | Caddy | nothing | routes to `web`, `bff`, `api` |
| `web` | Vite / static SPA | nothing | `edge` only |
| `bff` | Node + Fastify | `ui` schema | `api` (direct), `db` |
| `api` | Python + FastAPI | `crawl` schema | `db`, `render` |
| `worker` | Python | `crawl` schema | `db`, `render` |
| `render` | Node + Playwright | nothing (stateless) | — |
| `db` | PostgreSQL 18 | — | — |

**Data ownership.** One Postgres instance, two schemas, two migration chains.

- `bff` owns `ui`: schedules, saved views, operator preferences, notification
  settings. Migrations via a Node tool.
- `api`/`worker` own `crawl`: domains, templates, pages, observations, queue,
  runs, assets. Migrations via Alembic.
- **Neither service writes the other's schema.** The BFF starts a crawl by
  calling `POST /api/crawler/runs`, never by inserting a `runs` row. A grant
  that forbids cross-schema writes enforces this at the database, not by
  convention.

**Routing.** The edge gives the browser one origin, so there is no CORS
anywhere:

```
/                           → web    (SPA; static build in prod, Vite in dev)
/api/ui/*                   → bff
/api/crawler/*              → api
/api/crawler/runs/*/events  → api    (SSE; buffering explicitly disabled)
```

**The BFF does not proxy the crawler API.** A pass-through layer means every
Python schema change needs a BFF change, which is work with no benefit. The
BFF owns scheduling and aggregation; everything else the browser needs from
Python goes straight there through the edge.

**BFF → API is direct**, on the docker network, not through the edge. A
gateway hop for server-to-server traffic inside one compose network is pure
latency.

**SSE bypasses the BFF entirely.** Proxying an event stream through a second
hop adds a buffering layer and a second place for it to break, for no gain.

## Consequences

- Scheduling is a genuine bounded context — *when* to crawl is not *how* to
  crawl — so the BFF owning it is a real separation rather than a layer.
- The render sidecar (ADR-0016) takes Chromium out of the worker image
  entirely.
- Each tier scales on its own axis: more workers for throughput, more render
  replicas for JS-heavy domains, one BFF forever.
- **Cost, and it is the main one:** six services instead of three for a
  single-user local tool. More to start, more to debug, more places a request
  can die. `make up` gets slower and a failure can now be in a routing rule
  rather than in code. This is accepted because the operator asked for the
  separation and the render split earns it on its own — but it is not free,
  and the simpler topology was defensible.
- **Watch the BFF for thinness.** If after phase 3 it is more than ~80%
  pass-through — if its only real work is forwarding — collapse it and move
  scheduling into Python. A BFF that owns five endpoints and proxies forty is
  a layer, not a tier. Re-read this ADR at the end of phase 3 and answer the
  question honestly.

## Alternatives considered

**No BFF; SPA talks to the Python API through the edge.** Simpler and
genuinely viable — scheduling could live in Python, which already owns the
run lifecycle. Rejected because the operator wants UI concerns separated, and
because a BFF does earn its place for SSE fan-in, screen-shaped aggregation
(the Domains screen needs domains + health + template counts) and keeping the
SPA from making four calls per screen.

**A full API gateway (Kong, APISIX, Envoy).** Rejected. Its value is auth
termination, rate limiting, multi-team routing and canary deploys. There is
one user, no auth, one team and no deploys. It would add an admin API, often
its own datastore, and a config surface — to do path routing that Caddy does
in twenty readable lines.

**Separate databases rather than schemas.** Rejected as premature. Schemas
give ownership enforcement via grants while keeping cross-context reporting
queries possible. Splitting to separate databases later is easy; joining them
back is not.
