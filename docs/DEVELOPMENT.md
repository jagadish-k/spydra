# Development environment

Everything runs in Docker (ADR-0010). There are no "first install Python"
instructions, and adding some would be a bug.

The one exception is `llama-server`, which runs natively on the host because
Docker Desktop on macOS has no Metal GPU passthrough (ADR-0009).

---

## Prerequisites

- Docker Desktop (macOS). Give it at least **10 GB RAM and 6 CPUs** — seven
  containers, one of which runs Chromium. On a 16 GB machine see
  _Developing on a smaller machine_ below before setting this, because
  Docker and `llama-server` are competing for the same memory.
- `make`.
- `llama-server` built from llama.cpp, and a GGUF model. Optional until
  phase 4; everything else works without it.

That is the whole list. No Python, no Node, no Postgres on the host.

## First run

```sh
cp .env.example .env          # defaults work; nothing secret in it
make up                       # builds images, starts db/api/worker/web
make migrate                  # creates the schema
```

`make seed-dev` arrives with BUILD_PLAN 5.1; until then it skips.

**Use `http://localhost:8080` for everything.** It is the edge, it is one
origin, and it is what the SPA talks to. The ports below are published in
development for direct inspection only.

| What                         | URL                                  |
| ---------------------------- | ------------------------------------ |
| **The app**                  | **http://localhost:8080**            |
| Crawler API through the edge | http://localhost:8080/api/crawler    |
| BFF through the edge         | http://localhost:8080/api/ui         |
| Crawler OpenAPI docs         | http://localhost:8000/docs           |
| BFF OpenAPI docs             | http://localhost:3000/docs           |
| Render sidecar health        | http://localhost:3001/healthz        |
| Postgres                     | localhost:5432 (`spydra` / `spydra`) |

`make down` stops and keeps data. `make reset` drops the database volume.

## Verify what is built

There is no API or UI until phase 3. Today you verify the crawler three ways,
all offline against the fixture site in `backend/tests/fixtures/`.

### 1. The gates (what CI runs)

```sh
make check          # lint, types, all test suites, generated-file drift
make phase1-exit    # phase 1's exit: both fetchers, then render stopped
```

`make phase1-exit` uses the test database and prints a checklist ending
`✓ phase 1 exit`.

### 2. Crawl by hand and look at the rows

After `make up` and `make migrate`:

```sh
# the fixture site (test-only, behind a profile; no host port)
docker compose --profile phase1-exit up -d --wait fixtures

# three domains: static, rendered, auto. The running worker crawls them.
make load f=tests/fixtures/phase1/render-up.yaml
make logs           # worker: run_finished within a few seconds; Ctrl-C
```

```sh
make psql
```

```sql
SELECT p.url, o.strategy, o.http_status, o.title, o.price_amount, o.price_currency
FROM crawl.page_observations o JOIN crawl.pages p ON p.id = o.page_id
ORDER BY o.id DESC LIMIT 5;

SELECT id, state, stats FROM crawl.runs ORDER BY id DESC LIMIT 2;
SELECT source_url, state FROM crawl.asset_queue ORDER BY id DESC LIMIT 5;
```

Expected: three rows with `strategy = selector`, titles filled, the vantage
price in `GBP`, the run `completed`, asset rows `pending` (they are drained in
phase 5).

Then stop the browser and crawl again:

```sh
docker compose stop render
make load f=tests/fixtures/phase1/render-down.yaml
```

The vantage (static) page still extracts; the orbis (`auto`) page records
`strategy = static_fallback` with no title. Put things back with
`docker compose up -d render` and
`docker compose --profile phase1-exit stop fixtures`.

### 3. The render sidecar's isolation (ADR-0038)

A crawled page must not reach `db`/`api`/`bff`. On Linux this is measured. **On
Docker Desktop it is not yet**: please run this once and report the result.

```sh
docker compose exec render node -e "
for (const u of ['http://host.docker.internal:8000/', 'http://host.docker.internal:5432/'])
  fetch(u).then(r => console.log(u, 'REACHED', r.status), e => console.log(u, 'blocked', e.cause?.code));"
```

Pass: `blocked ENOTFOUND` or `blocked ECONNREFUSED` on both (Linux prints
`ENOTFOUND`). Anything else — `REACHED`, or another code such as
`UND_ERR_SOCKET` on `:5432` — means a page can reach the host's dev ports
(open question in `.tasks/fix-2.0-phase1-decisions.md`).

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

## Developing on a smaller machine

The target machine is a Mac Studio Ultra. Development happens on whatever you
have, and a 16 GB MacBook Pro is fine — but the memory budget stops being
generous, and the two consumers fight each other.

### The budget

On 16 GB, roughly **9–11 GB** is available to everything you care about, with
macOS taking the rest.

| Consumer           | Target machine | 16 GB machine                              |
| ------------------ | -------------- | ------------------------------------------ |
| Docker Desktop     | 10 GB          | **6 GB**                                   |
| Model weights      | ~20 GB         | ~5 GB                                      |
| KV cache / context | generous       | **the thing you will actually run out of** |

**Lower Docker's allocation before blaming the model.** The default
prerequisite of 10 GB plus a 5 GB model does not fit, and the symptom is not
an out-of-memory error — it is Chromium in the `render` container dying in
ways that look like random timeouts. If you are not working on rendering,
`docker compose stop render` and get 1–2 GB back.

### Which model

| Use               | Model               | Q4_K_M    | Note                                             |
| ----------------- | ------------------- | --------- | ------------------------------------------------ |
| Target (ADR-0020) | Qwen3-Coder 30B-A3B | ~20 GB    | MoE; ~3 B active params                          |
| Escalation        | Qwen 3.6 27B dense  | ~22 GB    | fields scoring below 60                          |
| **Development**   | **Qwen3-Coder 8B**  | **~5 GB** | or Qwen 3.5 9B if the coder build is unavailable |

```sh
llama-server -m ~/models/qwen3-coder-8b-q4_k_m.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 16384 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --flash-attn --n-gpu-layers 999
```

Set `LLM_MODEL=qwen3-coder-8b` in `.env` so proposals record which model
produced them (spec 013 §2) — a drawer full of 8B-authored templates is worth
being able to find later.

### Context is the real constraint, not parameters

A 3,000-node skeleton is 15–25k tokens. At 32k context the KV cache alone
costs more than the weights of an 8B model, so the two settings above —
`--ctx-size 16384` and a quantised KV cache — matter more than the model
choice does.

Cap the skeleton lower while developing:

```sh
SKELETON_MAX_NODES=1200        # spec 007 §2; 3000 on the target machine
LLM_SAMPLES=3                  # ADR-0020 says 5; 3 while iterating
```

Both are environment overrides precisely so the defaults stay honest in the
code and the laptop does not quietly become the specification.

### A weak model is a good test, within limits

Best-of-N plus deterministic verification exists to turn mediocre proposals
into usable templates by discarding most of them. An 8B produces more junk,
which exercises the discard path, the escalation path and the
"no candidate survived verification" UI state far harder than a 30B that is
usually right first time. Develop against it deliberately.

**What you must not do is calibrate on it.** `N=5`, `temperature 0.7` and the
score-60 escalation threshold were chosen for a 30B-class model (ADR-0020).
On an 8B the scores sit lower, and "fixing" the threshold to make the laptop
behave bakes a laptop constant into the product.

- Tests assert that ranking **works** — that a better selector outscores a
  worse one — never that a particular field clears 60.
- The constants are read from config, and the test suite fails if a test
  hard-codes one.
- Calibrate on the Studio, with the real model, once there is real traffic.

### Most of the build needs no model at all

Phases 0–3 are roughly two thirds of `BUILD_PLAN.md` and use the `LLMClient`
fake (task `4.1`). `make check` never starts `llama-server`. If you are
working on the scheduler, discovery, the API or the UI, do not run a model —
you will get the RAM back and the tests will be faster and deterministic.

---

## Compose topology

Seven services. Full rationale in
[`specs/010-service-topology.md`](specs/010-service-topology.md).

```yaml
# compose.yaml
name: spydra

x-py-env: &py-env
  DATABASE_URL: postgresql+asyncpg://spydra_api:spydra@db:5432/spydra
  LLM_BASE_URL: http://host.docker.internal:8080
  ASSET_ROOT: /data/assets
  HTML_CACHE_ROOT: /data/html
  LOG_LEVEL: ${LOG_LEVEL:-info}

# Every inspection port binds to 127.0.0.1 only. On Docker Desktop a
# container can probe the host's published ports via host.docker.internal;
# loopback-only binding is what keeps the render sidecar's isolation real
# (ADR-0023). Binding any of these to 0.0.0.0 reopens the boundary.

services:
  edge:
    image: caddy:2-alpine
    volumes:
      - ./docker/Caddyfile:/etc/caddy/Caddyfile:ro
    ports: ["127.0.0.1:8080:8080"]
    depends_on: [api, bff, web]

  db:
    image: postgres:18
    environment:
      POSTGRES_USER: spydra
      POSTGRES_PASSWORD: spydra
      POSTGRES_DB: spydra
    volumes:
      # postgres 18 requires the mount at the parent, not .../data — the old
      # path is a hard error from the image itself
      # (docker-library/postgres#1259)
      - pgdata:/var/lib/postgresql
      - ./docker/init-schemas.sql:/docker-entrypoint-initdb.d/10-schemas.sql:ro
    ports: ["127.0.0.1:5432:5432"]
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
      - ./backend:/app # bind: source, hot reload
      - venv:/app/.venv # named: never the bind mount
      - ${SPYDRA_DATA:-./.data}:/data
    extra_hosts: ["host.docker.internal:host-gateway"] # llama-server (ADR-0009)
    ports: ["127.0.0.1:8000:8000"]

  worker:
    build: { context: ., dockerfile: docker/worker.Dockerfile }
    command: python -m spydra.worker
    environment:
      <<: *py-env
      RENDER_BASE_URL: http://render:3001 # over render-link — ADR-0038
    depends_on:
      db: { condition: service_healthy }
    volumes:
      - ./backend:/app
      - venv:/app/.venv
      - ${SPYDRA_DATA:-./.data}:/data
    extra_hosts: ["host.docker.internal:host-gateway"] # llama-server (ADR-0009)
    networks: [default, render-link]
    deploy:
      replicas: 1 # politeness is enforced in the DB; raise freely
    # NOTE: no depends_on render. A rendered domain stalls honestly when the
    # sidecar is down; static crawling is unaffected (ADR-0016).

  render:
    build: { context: ., dockerfile: docker/render.Dockerfile }
    environment:
      RENDER_CONTEXTS: ${RENDER_CONTEXTS:-3}
      RECYCLE_AFTER_PAGES: 500
    shm_size: 1gb # Chromium crashes oddly on the 64 MB default
    # egress is the way out; render-link is the worker's way in (ADR-0038).
    # No network with db/api/bff; the sidecar refuses browser requests.
    networks: [egress, render-link]
    ports: ["127.0.0.1:3001:3001"] # dev inspection only, not the fetch path
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://localhost:3001/healthz').then(r=>process.exit(r.ok?0:1))",
        ]
      interval: 10s

  bff:
    build: { context: ., dockerfile: docker/bff.Dockerfile }
    command: npm run dev
    environment:
      DATABASE_URL: postgres://spydra_bff:spydra@db:5432/spydra
      CRAWLER_API_BASE: http://api:8000 # direct, not through the edge
      LOG_LEVEL: ${LOG_LEVEL:-info}
    depends_on:
      db: { condition: service_healthy }
    volumes:
      - ./bff:/app
      - .:/repo # prettier over root-level docs and yaml, via make
        # fmt-staged-js — no other container sees them
      - bff_modules:/app/node_modules # named: platform binaries
    ports: ["127.0.0.1:3000:3000"]

  web:
    build: { context: ., dockerfile: docker/web.Dockerfile }
    command: npm run dev -- --host 0.0.0.0
    environment:
      VITE_API_BASE: "" # same origin via the edge
    volumes:
      - ./frontend:/app
      - ./design:/design:ro # theme.css imports design/tokens/* (ADR-0018)
      - web_modules:/app/node_modules
    ports: ["127.0.0.1:5173:5173"]

networks:
  default: # api, worker, bff, db, edge, web
  egress: # render only — its way out
  render-link: # worker ↔ render only (ADR-0038)
    internal: true

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
and the Python venv are _never_ on the bind mount. `esbuild`, Pillow and
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

`docker/init-schemas.sql` runs once on first boot and creates the `crawl`
schema and the two roles with the grants that enforce ownership (spec 010
§3). The `ui` schema is created by the BFF's first Drizzle migration, so
`spydra_bff` owns it outright — which is also why the role carries
`CREATE ON DATABASE` (drizzle's ledger needs it; PG 18 checks the privilege
even for `CREATE SCHEMA IF NOT EXISTS` on an existing schema, and
db-level CREATE grants nothing inside `crawl`). The BFF role gets `SELECT`
on `crawl` and nothing more. **An `INSERT` into `crawl.runs` from the BFF
must fail** — that is the boundary, enforced by Postgres rather than by
convention.

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

## Working from a different tool

The repository is not tied to one coding tool. `AGENTS.md` is the anchor —
Claude Code, Cursor, OpenCode and Antigravity all read it with no
configuration — and the agent roles in `docs/agents/` are generated into each
tool's own format by `make agents` (`docs/WORKFLOW.md` §3).

```sh
make agents          # after editing any role in docs/agents/
```

Everything that actually enforces anything is tool-independent: `make check`,
the git hooks in `.githooks/`, and the Postgres grants. A tool's own hook
system can catch a mistake earlier — the Claude Code `PreToolUse` guard stops
an edit to a generated file before it happens — but nothing depends on it.

The one place tools genuinely differ is per-role permissions. Claude Code
takes a tool allowlist; **OpenCode v2 takes ordered `permissions` rules and
is the strictest of the four** — its model covers the shell as well as the
filesystem, so the reviewer is denied `edit` and `shell` outright with
`git diff`/`log`/`show`/`status` allowed back, and every read-write role is
denied edits to generated files and `drizzle-kit push`. Cursor and
Antigravity have no equivalent, so there `read-only` is prose. Full table in
`docs/agents/README.md`.

---

## Database access

Two chains, two owners, one database.

| Schema  | Owner            | Tool            | Migrations                     |
| ------- | ---------------- | --------------- | ------------------------------ |
| `crawl` | `api` / `worker` | SQLAlchemy Core | Alembic, `backend/migrations/` |
| `ui`    | `bff`            | **Drizzle**     | `drizzle-kit`, `bff/drizzle/`  |

```ts
// bff/drizzle.config.ts — schemaFilter is load-bearing
export default defineConfig({
  schema: "./src/db/schema/ui.ts",
  out: "./drizzle",
  dialect: "postgresql",
  schemaFilter: ["ui"], // a generated migration can never touch crawl
  dbCredentials: { url: process.env.DATABASE_URL! },
});
```

**The BFF reads `crawl` through generated types it must never hand-edit.**
`make drizzle-pull` introspects the live schema into
`bff/src/db/schema/crawl.generated.ts`; `make check` regenerates it and fails
on a diff. An Alembic migration that changes `crawl` therefore breaks the BFF
build, which is the correct moment to find out rather than the alternative.

`drizzle-kit push` is forbidden (ADR-0021). It applies a diff with no
migration file, no down path and nothing to review, and `make migrate-down`
is part of the test suite.

---

## Commands

Every target runs in Docker.

```sh
make up / down / reset / logs / ps
make shell-api            # bash in the api container
make shell-bff
make shell-web
make psql                 # psql into the dev database

make migrate              # both chains: alembic (crawl) + drizzle (ui)
make migrate-down         # one step back, both; CI asserts this works
make revision m="..."     # autogenerate a crawl migration (alembic)
make revision-ui m="..."  # generate a ui migration (drizzle-kit generate)
make drizzle-pull         # re-introspect crawl → crawl.generated.ts
make drizzle-studio       # optional: browse the ui schema

make test                 # everything
make test-api             # pytest
make test-bff             # the BFF suite
make test-web             # vitest
make e2e                  # Playwright against the running stack

make storybook            # the component workshop on 127.0.0.1:6006 (ADR-0043)
make storybook-build      # smoke-build every story; CI runs this before chromatic
make chromatic            # publish the build to Chromatic (needs the token)

make lint                 # ruff + mypy + import-linter + eslint + prettier
make fmt                  # ruff format + prettier --write
make types                # regenerate BOTH API schemas (crawler + ui)
make agents               # docs/agents/ → claude · cursor · opencode · antigravity
make generated            # types + drizzle-pull + agents. check fails on a diff

make check                # lint + test + types-clean.  CI runs exactly this.
```

`make check` is the gate. If it passes locally it passes in CI, because they
are the same command in the same images.

---

## Troubleshooting

| Symptom                                           | Cause                                                                                 | Fix                                                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Vite does not reload                              | inotify not delivered over the bind mount                                             | `usePolling: true` (above)                                                                                   |
| `esbuild`/`lxml` "invalid ELF header"             | host `node_modules` or venv leaked into the container                                 | `make reset-deps`; check the named volumes                                                                   |
| `host.docker.internal` unresolved                 | missing `extra_hosts`                                                                 | add it to the service                                                                                        |
| `llama-server` refused                            | not running on the host, or bound to something other than 127.0.0.1:8080              | start it; check the port                                                                                     |
| API reloads on every file touch                   | `--reload` watching `/data`                                                           | keep `--reload-dir /app/spydra`                                                                              |
| Postgres slow                                     | data on a bind mount                                                                  | it must be the `pgdata` named volume                                                                         |
| Disk fills fast                                   | asset and HTML accumulation                                                           | `make purge-html`; check the 7-day TTL sweep                                                                 |
| SSE arrives all at once at the end                | `flush_interval -1` missing or the SSE rule is below the general one in the Caddyfile | fix the Caddyfile ordering                                                                                   |
| Render times out randomly                         | `/dev/shm` too small                                                                  | `shm_size: 1gb` on `render`                                                                                  |
| Render times out randomly **on a 16 GB machine**  | Docker and `llama-server` are fighting for RAM                                        | lower Docker's allocation, or stop `render` while working on the model                                       |
| `llama-server` fails to allocate on Apple silicon | GPU-wired memory capped below physical                                                | raise `iogpu.wired_limit_mb`, or use a smaller quant                                                         |
| Proposals score far lower than the spec implies   | developing against an 8B                                                              | expected — see _Developing on a smaller machine_. Do not lower the threshold                                 |
| BFF cannot write `crawl.*`                        | **working as designed**                                                               | call the crawler API; do not loosen the grant                                                                |
| `rendered` domains stall, static fine             | sidecar down                                                                          | `docker compose ps render`; check `/healthz`                                                                 |
| Chromium driver mismatch                          | npm Playwright version ≠ image tag                                                    | pin them together                                                                                            |
| `make check` fails on a `crawl.generated.ts` diff | an Alembic migration changed `crawl`                                                  | `make drizzle-pull` and commit it. **Do not edit the generated file**                                        |
| A drizzle migration contains `crawl` DDL          | `schemaFilter` missing from `drizzle.config.ts`                                       | add it; delete and regenerate the migration                                                                  |
| Pre-commit is slow                                | it is running the full suite                                                          | it should not — pre-commit is format + lint + typecheck; `make check` belongs on pre-push. See `WORKFLOW.md` |
| A hook blocks a commit you believe is fine        | the gate is doing its job                                                             | fix it, or `--no-verify` **and say so in the PR**. Do not disable the hook                                   |
| pre-push: “a tree you are not pushing”            | the pushed ref is not `HEAD`, or the tree has changes the commit lacks                | check out that branch; commit or `git stash -u`. Never `--no-verify` past it                                 |
| An agent role change seems to have no effect      | you edited a generated copy                                                           | roles are edited in `docs/agents/`, then `make agents` (`WORKFLOW.md` §3)                                    |
| `make check` fails on `.cursor/` or `.agents/`    | `docs/agents/` changed without regenerating                                           | `make agents` and commit the result                                                                          |

## Configuration

`.env.example` is committed; `.env` is not. Nothing in either is secret —
this is a localhost tool with no third-party credentials. If that ever changes,
the secret does not go in the repo.

```sh
LOG_LEVEL=info
SPYDRA_DATA=./.data            # host path for /data
LLM_BASE_URL=http://host.docker.internal:8080
LLM_MODEL=qwen3-coder-30b-a3b  # qwen3-coder-8b when developing on a laptop
LLM_SAMPLES=5                  # ADR-0020; 3 while iterating on a laptop
SKELETON_MAX_NODES=3000        # spec 007 §2; 1200 on a laptop
RENDER_BASE_URL=http://render:3001
RENDER_CONTEXTS=3              # the sidecar's hard cap
ASSET_BOX=1200x1200
HTML_TTL_DAYS=7
PAGE_WORKERS=12
ASSET_WORKERS=24
```
