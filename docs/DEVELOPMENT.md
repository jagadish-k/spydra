# Development environment

Everything runs in Docker (ADR-0010). There are no "first install Python"
instructions, and adding some would be a bug.

The one exception is `llama-server`, which runs natively on the host because
Docker Desktop on macOS has no Metal GPU passthrough (ADR-0009).

---

## Prerequisites

- Docker Desktop (macOS). Give it at least **10 GB RAM and 6 CPUs** — seven
  containers, one of which runs Chromium.
- `make`.
- `llama-server` built from llama.cpp, and a GGUF model. Optional until
  phase 4; everything else works without it.

That is the whole list. No Python, no Node, no Postgres on the host.

## First run

```sh
cp .env.example .env          # defaults work; nothing secret in it
make up                       # builds images, starts db/api/worker/web
make migrate                  # creates the schema
make seed-dev                 # optional: two fixture domains, offline
```

**Use `http://localhost:8080` for everything.** It is the edge, it is one
origin, and it is what the SPA talks to. The ports below are published in
development for direct inspection only.

| What | URL |
| --- | --- |
| **The app** | **http://localhost:8080** |
| Crawler API through the edge | http://localhost:8080/api/crawler |
| BFF through the edge | http://localhost:8080/api/ui |
| Crawler OpenAPI docs | http://localhost:8000/docs |
| BFF OpenAPI docs | http://localhost:3000/docs |
| Render sidecar health | http://localhost:3001/healthz |
| Postgres | localhost:5432 (`spydra` / `spydra`) |

`make down` stops and keeps data. `make reset` drops the database volume.

## llama-server on the host

```sh
llama-server -m ~/models/<model>.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 16384 --n-gpu-layers 999
```

Containers reach it at `host.docker.internal:8080`, which requires
`extra_hosts: ["host.docker.internal:host-gateway"]` on each service that
calls it. The sidebar footer shows its reachability; `GET /api/health`
reports it.

**It is not required for crawling.** If it is down, onboarding blocks and
crawling is unaffected (ADR-0005).

---

## Compose topology

Seven services. Full rationale in
[`specs/010-service-topology.md`](specs/010-service-topology.md).

```yaml
# compose.yaml
name: spydra

x-py-env: &py-env
  DATABASE_URL: postgresql+asyncpg://spydra_api:spydra@db:5432/spydra
  RENDER_BASE_URL: http://render:3001
  LLM_BASE_URL: http://host.docker.internal:8080
  ASSET_ROOT: /data/assets
  HTML_CACHE_ROOT: /data/html
  LOG_LEVEL: ${LOG_LEVEL:-info}

services:
  edge:
    image: caddy:2-alpine
    volumes:
      - ./docker/Caddyfile:/etc/caddy/Caddyfile:ro
    ports: ["8080:8080"]
    depends_on: [api, bff, web]

  db:
    image: postgres:18
    environment:
      POSTGRES_USER: spydra
      POSTGRES_PASSWORD: spydra
      POSTGRES_DB: spydra
    volumes:
      - pgdata:/var/lib/postgresql/data           # named volume: performance
      - ./docker/init-schemas.sql:/docker-entrypoint-initdb.d/10-schemas.sql:ro
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U spydra"]
      interval: 5s
      retries: 10

  api:
    build: { context: ., dockerfile: docker/api.Dockerfile }
    command: uvicorn spydra.api.main:app --host 0.0.0.0 --port 8000
             --reload --reload-dir /app/spydra
    environment: *py-env
    depends_on:
      db: { condition: service_healthy }
    volumes:
      - ./backend:/app                            # bind: source, hot reload
      - venv:/app/.venv                           # named: never the bind mount
      - ${SPYDRA_DATA:-./.data}:/data
    extra_hosts: ["host.docker.internal:host-gateway"]
    ports: ["8000:8000"]

  worker:
    build: { context: ., dockerfile: docker/worker.Dockerfile }
    command: python -m spydra.worker
    environment: *py-env
    depends_on:
      db: { condition: service_healthy }
    volumes:
      - ./backend:/app
      - venv:/app/.venv
      - ${SPYDRA_DATA:-./.data}:/data
    extra_hosts: ["host.docker.internal:host-gateway"]
    deploy:
      replicas: 1        # politeness is enforced in the DB; raise freely
    # NOTE: no depends_on render. A rendered domain stalls honestly when the
    # sidecar is down; static crawling is unaffected (ADR-0016).

  render:
    build: { context: ., dockerfile: docker/render.Dockerfile }
    environment:
      RENDER_CONTEXTS: ${RENDER_CONTEXTS:-3}
      RECYCLE_AFTER_PAGES: 500
    shm_size: 1gb        # Chromium crashes oddly on the 64 MB default
    networks: [egress]   # NOT on the internal network — see below
    ports: ["3001:3001"]
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://localhost:3001/healthz').then(r=>process.exit(r.ok?0:1))"]
      interval: 10s

  bff:
    build: { context: ., dockerfile: docker/bff.Dockerfile }
    command: npm run dev
    environment:
      DATABASE_URL: postgres://spydra_bff:spydra@db:5432/spydra
      CRAWLER_API_BASE: http://api:8000      # direct, not through the edge
      LOG_LEVEL: ${LOG_LEVEL:-info}
    depends_on:
      db: { condition: service_healthy }
    volumes:
      - ./bff:/app
      - bff_modules:/app/node_modules       # named: platform binaries
    ports: ["3000:3000"]

  web:
    build: { context: ., dockerfile: docker/web.Dockerfile }
    command: npm run dev -- --host 0.0.0.0
    environment:
      VITE_API_BASE: ""                     # same origin via the edge
    volumes:
      - ./frontend:/app
      - web_modules:/app/node_modules
    ports: ["5173:5173"]

networks:
  default:              # api, worker, bff, db, edge, web
  egress:               # render only — no route to db/api/bff

volumes:
  pgdata:
  venv:
  bff_modules:
  web_modules:
```

### Five details that are not optional

**1. The render sidecar is on its own network.** It fetches arbitrary
operator-supplied URLs with a real browser — the largest attack surface here.
A crawled page must not be able to reach `http://db:5432` or
`http://api:8000/api/crawler/domains`. Separate network, no route inward.
This is cheap and it is the only real isolation boundary in the stack.

**2. `shm_size: 1gb` on `render`.** Chromium's default 64 MB `/dev/shm`
causes crashes that present as random timeouts and will cost you a day.

**3. Dependency directories live in named volumes.** `node_modules` (twice)
and the Python venv are *never* on the bind mount. `esbuild`, Pillow and
`selectolax` ship platform-specific binaries; if the host's copy is visible
to the container they fight, and the failure looks like a corrupted install
rather than a mount problem.

**4. Vite needs polling.** macOS bind mounts do not deliver inotify events
reliably:

```ts
// vite.config.ts
server: {
  host: "0.0.0.0",
  port: 5173,
  watch: { usePolling: true, interval: 300 },
  hmr: { clientPort: 5173 },
}
```

Polling costs CPU. It is the price of docker-native on macOS (ADR-0010).

**5. `/data` is a bind mount, not a named volume.** Images and HTML
snapshots should be visible in Finder, backed up by Time Machine, and survive
`docker compose down -v`. Postgres is the opposite — named volume, better
performance, not meant to be browsable.

### Database roles

`docker/init-schemas.sql` runs once on first boot and creates the two schemas
and two roles with the grants that enforce ownership (spec 010 §3). The BFF
role gets `SELECT` on `crawl` and nothing more. **An `INSERT` into
`crawl.runs` from the BFF must fail** — that is the boundary, enforced by
Postgres rather than by convention.

### Caddyfile

`docker/Caddyfile`, reproduced in spec 010 §2. The line that matters:

```caddyfile
handle /api/crawler/runs/*/events {
    reverse_proxy api:8000 {
        flush_interval -1          # ← without this, SSE buffers and breaks
    }
}
```

This rule must come **before** the general `/api/crawler/*` rule.

### Playwright lives in the sidecar only

`docker/render.Dockerfile` is built from `mcr.microsoft.com/playwright:v1.x-noble`
(the **Node** flavour), so Chromium and its system libraries are present. Do
**not** run `playwright install` at container start — it re-downloads
browsers on every boot. Pin the npm package to the same version as the image
tag or the driver and browser will mismatch.

**The Python images contain no browser and no `playwright` package.** If you
find yourself adding one, read ADR-0016 — rendering goes over HTTP to
`render:3001`.

---

## Commands

Every target runs in Docker.

```sh
make up / down / reset / logs / ps
make shell-api            # bash in the api container
make shell-bff
make shell-web
make psql                 # psql into the dev database

make migrate              # both chains: alembic (crawl) + the BFF's (ui)
make migrate-down         # one step back, both; CI asserts this works
make revision m="..."     # autogenerate a crawl migration
make revision-ui m="..."  # a ui migration

make test                 # everything
make test-api             # pytest
make test-bff             # the BFF suite
make test-web             # vitest
make e2e                  # Playwright against the running stack

make lint                 # ruff + mypy + import-linter + eslint + prettier
make fmt                  # ruff format + prettier --write
make types                # regenerate BOTH schemas (crawler + ui)

make check                # lint + test + types-clean.  CI runs exactly this.
```

`make check` is the gate. If it passes locally it passes in CI, because they
are the same command in the same images.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Vite does not reload | inotify not delivered over the bind mount | `usePolling: true` (above) |
| `esbuild`/`lxml` "invalid ELF header" | host `node_modules` or venv leaked into the container | `make reset-deps`; check the named volumes |
| `host.docker.internal` unresolved | missing `extra_hosts` | add it to the service |
| `llama-server` refused | not running on the host, or bound to something other than 127.0.0.1:8080 | start it; check the port |
| API reloads on every file touch | `--reload` watching `/data` | keep `--reload-dir /app/spydra` |
| Postgres slow | data on a bind mount | it must be the `pgdata` named volume |
| Disk fills fast | asset and HTML accumulation | `make purge-html`; check the 7-day TTL sweep |
| SSE arrives all at once at the end | `flush_interval -1` missing or the SSE rule is below the general one in the Caddyfile | fix the Caddyfile ordering |
| Render times out randomly | `/dev/shm` too small | `shm_size: 1gb` on `render` |
| BFF cannot write `crawl.*` | **working as designed** | call the crawler API; do not loosen the grant |
| `rendered` domains stall, static fine | sidecar down | `docker compose ps render`; check `/healthz` |
| Chromium driver mismatch | npm Playwright version ≠ image tag | pin them together |

## Configuration

`.env.example` is committed; `.env` is not. Nothing in either is secret —
this is a localhost tool with no third-party credentials. If that ever changes,
the secret does not go in the repo.

```sh
LOG_LEVEL=info
SPYDRA_DATA=./.data            # host path for /data
LLM_BASE_URL=http://host.docker.internal:8080
LLM_MODEL=qwen3-30b-a3b
RENDER_BASE_URL=http://render:3001
RENDER_CONTEXTS=3              # the sidecar's hard cap
ASSET_BOX=1200x1200
HTML_TTL_DAYS=7
PAGE_WORKERS=12
ASSET_WORKERS=24
```
