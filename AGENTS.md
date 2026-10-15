# AGENTS.md

Operating rules for any agent working in this repository. Read this first,
every session. It is deliberately short; the detail lives in `docs/`.

---

## What this is

**Spydra** — a single-user, locally-hosted crawler that extracts structured
product data from bespoke supplier sites. A local LLM *proposes* extraction
rules; the operator approves them before any domain goes live. The model never
runs during a crawl.

There is exactly one user. No authentication, no multi-tenancy, no horizontal
scaling. Do not add them.

## Read before writing code

| Doc | When |
| --- | --- |
| `docs/specs/010-service-topology.md` | **First.** Six services, routing, who owns which data. |
| `docs/ARCHITECTURE.md` | Always. The source of truth for system design. |
| `docs/BUILD_PLAN.md` | Always. Tells you which phase you are in and what "done" means. |
| `docs/adr/` | Before changing any structural decision. |
| `docs/specs/` | Before implementing a component. One spec per component. |
| `docs/DEVELOPMENT.md` | Before running anything. |
| `docs/DESIGN_SYSTEM.md` + `design/mockups/` | Before writing any UI. |

**The mockups in `design/mockups/` are the UI specification.** They are static
HTML, they open from disk with no build step, and they are accurate. Build the
React components to match them, not to match your own idea of the layout.

---

## Hard rules

1. **Docker-native. Everything runs in a container.** Do not install Python
   packages, Node packages, or Postgres on the host. If a command does not
   work through `make`, fix the `make` target rather than running it outside.
   The one exception is `llama-server`, which runs natively on the host
   because Docker Desktop on macOS has no Metal GPU passthrough (ADR-0007).
2. **Never commit secrets.** No API keys, no real supplier URLs in fixtures,
   no `.env` files. `.env.example` only.
3. **Do not add a message broker, a cache layer, or a second datastore.**
   Postgres is the queue and the database (ADR-0002). If you think you need
   Redis, you have misread the problem — read ADR-0002 and say so.
4. **A service owns its data and nobody else writes it.** `api`/`worker` own
   the `crawl` schema; `bff` owns `ui`. The BFF may `SELECT` from `crawl` and
   may never write to it — it starts a crawl by calling the API. Postgres
   grants enforce this; if you find yourself wanting to loosen a grant, stop
   (ADR-0015, spec 010 §3).
5. **The BFF does not proxy the crawler API.** If a BFF route only forwards,
   route it at the edge instead. A pass-through layer means every Python
   schema change becomes a BFF change.
6. **Do not use raw Tailwind palette classes.** `text-red-600` is a defect.
   Components consume semantic utilities only (`text-state-broken`,
   `bg-surface`). `design/tokens/tailwind-theme.css` removes the default
   palette so these fail to compile; do not re-add it.
7. **Do not remove the `--sp-*` prefix on design tokens.** Tailwind v4 claims
   `--text-*`, `--color-*`, `--radius-*` and others as theme namespaces, and
   an unprefixed `--text-primary` is silently read as a font size. The prefix
   is the only thing preventing that (ADR-0018).
8. **Never retry through a block.** A 403 or a 429 backs off and pauses the
   domain. A retry loop against a site that has decided to block you is how a
   temporary block becomes permanent.
9. **Every LLM proposal is verified deterministically** against the real DOM
   before a human sees it. No exceptions, no "the model was probably right".
10. **Templates are versioned, never edited in place.** Every observation
   records the template version that produced it.
11. **Observations are append-only.** Never `UPDATE` a `page_observations` row.
12. **No network calls in unit tests.** Use fixtures. `respx` for httpx,
    recorded HTML for parsers, a fake render service for the browser path.
13. **Do not change a public API shape without updating its spec and
    regenerating the frontend types** (`make types`). There are two schemas
    now — the crawler's and the BFF's.

---

## Services

Six, plus `llama-server` on the host. Full detail in spec 010.

| Service | What it is | Owns |
| --- | --- | --- |
| `edge` | Caddy. One origin, path routing, serves the SPA | — |
| `web` | React SPA | — |
| `bff` | Fastify. Scheduling, saved views, aggregation | `ui` schema |
| `api` | FastAPI. Domains, templates, runs, pages | `crawl` schema |
| `worker` | The crawler. Scales by replica | `crawl` schema |
| `render` | Playwright behind HTTP. Stateless | nothing |
| `db` | PostgreSQL | — |

```
/                          → web
/api/ui/*                  → bff
/api/crawler/*             → api
/api/crawler/runs/*/events → api   (SSE; edge buffering disabled)
```

## Stack

**Track the latest stable release of everything** (ADR-0017). Exact versions
live in the lockfiles; these are the majors.

**Backend** — Python 3.15 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 Core
(async, asyncpg) · Alembic · httpx · selectolax · extruct · Pillow ·
structlog. **No Playwright** — rendering is a sidecar (ADR-0016).

**BFF** — Node 26 · Fastify 5 · TypeScript strict · TypeBox · plain SQL

**Frontend** — React 19 · TypeScript strict · Vite · Tailwind v4 (CSS-first)
· TanStack Query · TanStack Table · React Router · react-hook-form + zod ·
Recharts

**Render sidecar** — Node 26 · Playwright, on the official Playwright image.
Pin the npm package to the image tag or driver and browser mismatch.

**Infrastructure** — Docker Compose · PostgreSQL 18 · Caddy ·
`llama-server` on the host at `host.docker.internal:8080`

**Tooling** — ruff · mypy (strict) · pytest · ESLint · Prettier · Vitest ·
Playwright

Do not introduce a new runtime dependency without an ADR. Before bumping a
Python major, check that every compiled dependency publishes a wheel for it
(ADR-0017) — verify on PyPI, do not discover it in a failing build.

---

## Commands

Every command is a `make` target and every target runs in Docker.

```sh
make up            # start edge, db, api, worker, render, bff, web
make down          # stop, keep volumes
make reset         # stop and DROP the database volume
make logs          # follow all services
make shell-api     # shell inside the api container
make shell-bff
make psql          # psql into the dev database (both schemas)

make migrate       # both chains: alembic (crawl) + the BFF's (ui)
make revision m="add asset_queue"   # autogenerate a crawl migration
make revision-ui m="add schedules"  # a ui migration

make test          # everything
make test-api      # pytest
make test-bff      # the BFF suite
make test-web      # vitest
make e2e           # Playwright against the running stack

make lint          # ruff + mypy + eslint + prettier --check
make fmt           # ruff format + prettier --write
make types         # regenerate BOTH frontend API schemas from OpenAPI

make check         # lint + test + types-is-clean. CI runs exactly this.
```

`make check` must pass before you consider any task done.

---

## Repository layout

```
backend/                   # api + worker (Python)
  spydra/
    domain/        # entities, value objects, pure logic. No I/O, no imports
                   # from adapters. If it touches the network or the DB it
                   # does not belong here.
    ports/         # Protocol classes: Frontier, Fetcher, Extractor,
                   # LLMClient, AssetStore, Clock
    adapters/
      postgres/    # repositories; raw SQL where the query is the point
      http/        # HttpxFetcher, PlaywrightFetcher
      llm/         # LlamaServerClient
      storage/     # LocalAssetStore
    extraction/
      strategies/  # structured.py, selector.py, llm_proposal.py
      chain.py     # ordered strategy chain
      validation.py
    scheduler/     # politeness gate, claim loop, asset gate
    api/           # FastAPI routers, schemas, SSE
    worker.py
  migrations/      # alembic
  tests/
bff/                       # Fastify — scheduling, saved views, aggregation
  src/
    routes/
    scheduler/     # the fire loop; see spec 011 §3
    db/            # ui schema, plain SQL + migrations
  tests/
render/                    # Playwright behind HTTP (spec 012)
  src/
  tests/
frontend/
  src/
    api/           # generated types + typed client. Do not hand-edit types.
                   #   schema.crawler.d.ts · schema.ui.d.ts
    components/    # design-system components; one per DESIGN_SYSTEM.md entry
    views/         # one per screen in docs/SCREENS.md
    hooks/
    lib/
    styles/        # theme.css → imports tokens + tailwind-theme
  tests/
docs/
design/            # tokens, logo, mockups. Treat as read-only reference.
docker/            # Dockerfiles + Caddyfile
compose.yaml
Makefile
```

**The `ports/` + `adapters/` split is load-bearing.** It is what makes the
Postgres-over-broker decision reversible, keeps Playwright out of the default
path, and lets extraction strategies be added without touching the chain that
orders them. Do not reach around it — the API layer talks to ports, never to
`asyncpg` directly.

---

## Conventions

**Python**

- `ruff` and `mypy --strict` both clean. No `# type: ignore` without a comment
  saying why.
- Public functions take and return domain types, not dicts.
- Async all the way down in the request and worker paths. No `time.sleep`.
- SQL that matters (the claim query, the diff views) is written as SQL in the
  Postgres adapter, not assembled by an ORM. SQLAlchemy is there for
  migrations, pooling and the boring CRUD.
- Errors: raise domain exceptions from `domain/`, translate to HTTP in `api/`.

**TypeScript**

- `strict: true`, `noUncheckedIndexedAccess: true`. No `any`; use `unknown`
  and narrow.
- Server state is TanStack Query. Local UI state is `useState` or context.
  Do not add a global store for things one screen needs.
- API types are generated (`make types`) from the backend's OpenAPI schema.
  Never hand-write a response interface.
- One component per file. Components under `components/` take props and render;
  they do not fetch.

**Both**

- Name things after the domain: `Frontier`, `Template`, `Observation`,
  `UnknownPage`. Not `Manager`, `Helper`, `Util`, `Service`.
- Comments explain *why*, never *what*. If you need a comment to say what the
  code does, rename the thing instead.
- Commit messages: imperative subject under 72 chars, body explains the
  reasoning when the change is not obvious.

---

## Definition of done

A task is done when all of these hold:

- [ ] `make check` passes.
- [ ] The behaviour is covered by a test that would fail without the change.
- [ ] If it touched the API, `docs/specs/005-api.md` is current and
      `make types` produced no diff.
- [ ] If it touched the schema, there is a migration and it runs both ways.
- [ ] If it touched the UI, it matches the mockup and works in both themes.
- [ ] If it changed a structural decision, there is an ADR.
- [ ] `docs/BUILD_PLAN.md` has the task ticked.

Not done: "it works on my machine", "tests are flaky but unrelated", "I will
add the migration next".

---

## When you are stuck or disagree

Say so, in the open, with the reasoning. The decisions in `docs/adr/` were
argued through and most have a stated cost. If you hit a case the ADR did not
anticipate, write a new ADR that supersedes it — do not quietly work around
it, and do not silently follow it off a cliff either.

If a spec and the code disagree, the spec is wrong until proven otherwise, but
**check whether the code was deliberate** before rewriting it.

If a task needs a capability this repo does not have — a skill, a tool, a
service — stop and say what is missing rather than approximating it.
