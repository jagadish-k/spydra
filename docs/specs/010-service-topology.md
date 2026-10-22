# 010 — Service topology

**Phase 0** · ADR-0015, ADR-0016 · everything else assumes this

Six services. The rule that keeps this from being a distributed monolith:
**a service owns its data and nobody else writes it.**

---

## 1. Services

| Service  | Image base                                | Port | Owns           | Scales              |
| -------- | ----------------------------------------- | ---- | -------------- | ------------------- |
| `edge`   | `caddy:2-alpine`                          | 8080 | —              | no                  |
| `web`    | `node:26-slim` (dev) / static (prod)      | 5173 | —              | no                  |
| `bff`    | `node:26-slim`                            | 3000 | `ui` schema    | no                  |
| `api`    | `python:3.15-slim`                        | 8000 | `crawl` schema | no                  |
| `worker` | `python:3.15-slim`                        | —    | `crawl` schema | **yes**, by replica |
| `render` | `mcr.microsoft.com/playwright:v1.x-noble` | 3001 | nothing        | **yes**, by replica |
| `db`     | `postgres:18`                             | 5432 | —              | no                  |

Plus `llama-server` on the host (ADR-0009). Seven things, one of which the
operator starts themselves.

**Networks.** `default` holds everything except `render`. `render` is on
`egress` (its way out) and `render-link`, an internal network whose only
other member is `worker`, which reaches it at `http://render:3001`. The same
topology runs on Linux Docker Engine and Docker Desktop
([ADR-0038](../adr/0038-render-link-network.md)). Adding a service to
`egress` or `render-link` gives a crawled page a route to it.

**Only `edge` publishes a port to the host in production.** In development
`api`, `bff` and `db` also publish, for direct inspection — convenience, not
architecture.

## 2. Routing

The edge gives the browser one origin. There is no CORS configuration
anywhere in this system, and if you find yourself adding some, the routing is
wrong.

```caddyfile
# docker/Caddyfile
:8080 {
	encode zstd gzip

	# SSE: straight to Python, no BFF hop, no buffering.
	# flush_interval -1 is the line that makes streaming work.
	handle /api/crawler/runs/*/events {
		reverse_proxy api:8000 {
			flush_interval -1
			transport http {
				response_header_timeout 24h
			}
		}
	}

	handle /api/crawler/* {
		reverse_proxy api:8000
	}

	handle /api/ui/* {
		reverse_proxy bff:3000
	}

	handle {
		reverse_proxy web:5173        # prod: file_server from the built SPA
	}
}
```

| Path                         | Goes to | Why                                               |
| ---------------------------- | ------- | ------------------------------------------------- |
| `/`                          | `web`   | the SPA                                           |
| `/api/ui/*`                  | `bff`   | scheduling, saved views, preferences, aggregation |
| `/api/crawler/*`             | `api`   | domains, templates, runs, pages, reports          |
| `/api/crawler/runs/*/events` | `api`   | SSE — matched **before** the general crawler rule |

**`flush_interval -1` is not optional.** Without it Caddy buffers the
response and the event stream arrives in chunks or not at all. This is the
single most likely thing to break when someone edits the Caddyfile.

**The BFF does not proxy the crawler API.** Pass-through means every Python
schema change becomes a BFF change — work with no benefit. If you are about
to add a BFF route that only forwards, route it at the edge instead.

**BFF → API is direct** (`http://api:8000`), not through the edge. A gateway
hop for server-to-server traffic on the same network is pure latency.

## 3. Data ownership

One Postgres instance, two schemas, two migration chains.

```sql
CREATE SCHEMA crawl;   -- owned by api/worker, migrated by Alembic
                         -- ui is NOT created here: the BFF's first Drizzle
                         -- migration creates AND owns it (ADR-0024)

CREATE ROLE spydra_api LOGIN PASSWORD '…';
CREATE ROLE spydra_bff LOGIN PASSWORD '…';

GRANT USAGE, CREATE ON SCHEMA crawl TO spydra_api;
GRANT CREATE ON DATABASE spydra TO spydra_bff;

-- The BFF may READ crawl data for aggregation, never write it.
GRANT USAGE ON SCHEMA crawl TO spydra_bff;
ALTER DEFAULT PRIVILEGES FOR ROLE spydra_api IN SCHEMA crawl
  GRANT SELECT ON TABLES TO spydra_bff;

-- The API has no access to ui at all.
```

**The grants are the enforcement.** Ownership stated in a document is a
convention someone will break under deadline; ownership stated in
`ALTER DEFAULT PRIVILEGES` is an error message. A BFF `INSERT` into
`crawl.runs` must fail at the database.

The BFF starts a crawl by calling `POST /api/crawler/runs`. It never inserts
a `runs` row, even though it can see the table.

## 4. Startup and health

```
db  ──healthy──> api ──┐
                       ├──> edge
db  ──healthy──> bff ──┘
render ──healthy──────────> (api and worker check it lazily)
```

- `db`: `pg_isready`.
- `api`: `GET /healthz` → `{db, render, llama_server, disk_free_bytes}`.
- `bff`: `GET /healthz` → `{db, api}`.
- `render`: `GET /healthz` → `{ok, contexts_in_use, contexts_max}`.
- `edge`: no healthcheck; if it is up it routes.

`worker` has no HTTP surface. Liveness is "it is claiming rows" — visible in
`crawl.crawl_queue` and in the run monitor, not in a healthcheck.

**`api` and `worker` do not hard-depend on `render`.** A rendered domain
fails honestly when it is down (ADR-0016); static crawling is unaffected.
`depends_on: render` would be wrong.

## 5. Failure matrix

| Down           | Effect                                                                     | Surfaced as                    |
| -------------- | -------------------------------------------------------------------------- | ------------------------------ |
| `edge`         | Nothing reachable                                                          | browser error                  |
| `web`          | SPA will not load; API still works via curl                                | browser error                  |
| `bff`          | Schedules do not fire; saved views unavailable. **Crawling unaffected**    | `/api/ui/*` 502; sidebar badge |
| `api`          | No control plane. Running worker drains its queue and stops                | SPA error state                |
| `worker`       | Queue stops draining; run never completes                                  | run monitor shows no progress  |
| `render`       | `rendered` domains stall; `auto` falls back to static; `static` unaffected | run monitor; `/healthz`        |
| `db`           | Everything stops                                                           | all healthchecks red           |
| `llama-server` | Onboarding blocked; **crawling unaffected**                                | sidebar dot                    |

Two of these are deliberate and worth restating: **the BFF being down does
not stop a crawl**, and **the render sidecar being down does not stop static
crawling**. If either ever becomes a hard dependency, the separation has been
lost.

## 6. Acceptance

- [ ] `make up` brings all six up; `GET :8080/api/crawler/healthz` returns 200.
- [ ] The SPA makes no cross-origin request (assert: no CORS header anywhere).
- [ ] An SSE stream through the edge delivers events **as they happen**, not
      batched at the end. Test with a stream that emits one event per second
      and assert on arrival times.
- [ ] `spydra_bff` attempting `INSERT INTO crawl.runs` is rejected by Postgres.
- [ ] `spydra_api` cannot see the `ui` schema.
- [ ] Stopping `bff` leaves an in-flight run completing normally.
- [ ] Stopping `render` leaves `static` domains crawling and marks `rendered`
      ones stalled rather than failed.
- [ ] `docker compose config` resolves with no hardcoded host ports in prod.
