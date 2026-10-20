# AGENTS.md

Operating rules for any agent working in this repository. Read this first,
every session. It is deliberately short; the detail lives in `docs/`.

**This file is the anchor.** Claude Code, Cursor, OpenCode and Antigravity all
read it without configuration, so it is the one place rules can live and be
seen by every tool. Whatever you are driving, start here.

**Working as part of the agent team?** Read [`docs/WORKFLOW.md`](docs/WORKFLOW.md)
too — it defines the branch model, the handoff protocol and which role owns
which part of a change. The roles themselves are in
[`docs/agents/`](docs/agents/), and `make agents` generates them into your
tool's format.

---

## What this is

**Spydra** — a single-user, locally-hosted crawler that extracts structured
product data from bespoke supplier sites. A local LLM _proposes_ extraction
rules; the operator approves them before any domain goes live. The model never
runs during a crawl.

There is exactly one user. No authentication, no multi-tenancy, no horizontal
scaling. Do not add them.

## Read before writing code

| Doc                                  | When                                                                         |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| `docs/specs/010-service-topology.md` | **First.** Six services, routing, who owns which data.                       |
| `docs/ARCHITECTURE.md`               | Always. Why the system is shaped this way.                                   |
| `docs/BUILD_PLAN.md`                 | Always. Tells you which phase you are in and what "done" means.              |
| `docs/adr/`                          | Before changing any structural decision.                                     |
| `docs/specs/`                        | Before implementing a component. One spec per component.                     |
| `docs/DEVELOPMENT.md`                | Before running anything.                                                     |
| `docs/SCREENS.md`                    | Before any UI work. The screen registry — what exists and where it is drawn. |
| `docs/UI_STATES.md`                  | Before writing any UI. Which states exist, per component and per screen.     |
| `docs/COMPONENTS.md`                 | Before building a component. What exists in Figma and what it is used by.    |
| `docs/DESIGN_SYSTEM.md`              | Before writing any UI. Tokens, and the one rule.                             |

**The UI specification is three artifacts, one axis each** (ADR-0031,
extending ADR-0025). They do not overlap.

1. **`docs/SCREENS.md` is the screen registry** — the single source of truth
   for which screens exist, how many, and where each is drawn. Nothing else
   enumerates screens. **Eleven screens · twelve top-level layouts · 62
   frames.** If you are counting screens, you are reading the wrong file; read
   the table.
2. **The Figma file is authoritative for what every state looks like** —
   layout, spacing, typography and colour, in all states. File
   `GeJPFXY4CicHBdzLMyXG2E`, page `🖥 Screens` (`3:139`). Node ids per screen
   are in the registry.
3. **`docs/UI_STATES.md` is authoritative for which states must exist** and
   what each must not do.

`design/mockups/` is a **runnable reference, not an authority**: real tokens in
a real browser with no Figma account, but one state of eleven. **Where it and
Figma disagree, Figma wins.** Where Figma and `UI_STATES.md` disagree about
whether a state should exist at all, `UI_STATES.md` wins.

**Never inventory the Figma file with a bare `get_metadata`.** It reports only
the pages loaded in the operator's editor and has answered "two pages" and
"four pages" to the same file minutes apart. Enumerate with
`figma.root.children` through `use_figma`, then query per page. ADR-0031 §7.

**Cardinal rule — anything above a primitive is a component** (ADR-0032). In
Figma, a screen frame is a **composition of instances**: if an element has
state, variants, repetition, or an identity you would name, it is a component
on the `🧩 Components` page and the frame holds an instance. Primitives are
layout containers, text nodes and page scaffolding — that list is closed.
Every component carries the properties its content needs; one with only
`VARIANT` properties and no `TEXT` property is incomplete, because it forces
the hand-drawing this rule prohibits. **No component hard-codes which of its
children is active** — that is a property, which is why the sidebar has
`Active=` and the topbar has `Breadcrumb`.

**A hand-drawn element that duplicates a component is a review finding.** Ten
remain in screens 1–10 (`docs/COMPONENTS.md` §2); screen 11 Schedules is the
worked example and contains none. **Build from the component.**

**Adding a text property to a component can silently reset existing instance
overrides** — it reset 5 of 300. Capture a baseline of the affected instances
before the change and compare after. Procedure, not advice.

---

## Hard rules

1. **Docker-native.** Do not install Python packages, Node packages, or
   Postgres on the host. If a command does not work through `make`, fix the
   `make` target rather than running it outside. Two deliberate exceptions:
   `llama-server`, which runs natively because Docker Desktop on macOS has no
   Metal GPU passthrough (ADR-0009); and `make agents` / `make hooks`, which
   are stdlib-Python and git respectively, because the gate has to work
   before any image exists and from any tool's terminal.
2. **Never commit secrets.** No API keys, no tokens, no credentials, no
   `.env` files — `.env.example` only. Test fixtures are **hand-written**
   HTML, not captured from anyone's site (BUILD_PLAN `1.4`): a fixture has
   to hold still for years, and a copy of a real page goes stale, carries
   someone else's content and tempts a test into reaching for the original.
   `docs/TARGETS.md` records example sites for the operator to try by hand,
   and nothing in the build depends on them.
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
   This includes selectors produced by chat and by the playground.
10. **One authoring pipeline.** Form, chat and playground are three front
    doors to one `TemplateDraft` and one verify/merge/rank path (ADR-0019).
    A second verification implementation, or a mode that writes `templates`
    directly, is a defect regardless of how well it works.
11. **No supplier HTML or script in the app document.** The page preview is a
    screenshot plus geometry from `POST /inspect` (spec 014 §1). No iframe, no
    `innerHTML` with fetched markup, no "just sanitised" exception.
12. **Templates are versioned, never edited in place.** Every observation
    records the template version that produced it.
13. **Observations are append-only.** Never `UPDATE` a `page_observations` row.
14. **No network calls in unit tests.** Use fixtures.
    `httpx2.MockTransport` for HTTP (ADR-0028 — a handler function, not a
    mocking library), recorded HTML for parsers, a fake render service for
    the browser path.
15. **Do not change a public API shape without updating its spec and
    regenerating the frontend types** (`make types`). Two schemas are
    generated — the crawler's and the BFF's.
16. **Generated files are never hand-edited.** `schema.crawler.d.ts`,
    `schema.ui.d.ts`, `bff/src/db/schema/crawl.generated.ts` and everything
    under `.claude/agents/`, `.cursor/rules/`, `.opencode/agents/` and
    `.agents/rules/` are build artifacts that happen to be committed.
    `make check` regenerates them and fails on a diff; editing one to make
    the build pass inverts the whole point (ADR-0013, ADR-0021, ADR-0022).
    Agent roles are edited in `docs/agents/`.
17. **`drizzle-kit push` is forbidden.** The BFF uses `generate` + `migrate`
    so every schema change is a reviewable file with a down path. `push`
    leaves no artifact and cannot satisfy `make migrate-down` (ADR-0021).
18. **Work on a branch, and let the gate decide.** `develop` is protected;
    every change arrives by PR from `type/NN-slug`. `make check` is the
    contract between one agent and the next — see `docs/WORKFLOW.md`.

---

## Services

Six, plus `llama-server` on the host. Full detail in spec 010.

| Service  | What it is                                      | Owns           |
| -------- | ----------------------------------------------- | -------------- |
| `edge`   | Caddy. One origin, path routing, serves the SPA | —              |
| `web`    | React SPA                                       | —              |
| `bff`    | Fastify. Scheduling, saved views, aggregation   | `ui` schema    |
| `api`    | FastAPI. Domains, templates, runs, pages        | `crawl` schema |
| `worker` | The crawler. Scales by replica                  | `crawl` schema |
| `render` | Playwright behind HTTP. Stateless               | nothing        |
| `db`     | PostgreSQL                                      | —              |

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
(async, asyncpg) · Alembic · **httpx2** · selectolax · extruct · Pillow ·
structlog. **No Playwright** — rendering is a sidecar (ADR-0016).

httpx2, not httpx (ADR-0028): httpx is winding down, Starlette's TestClient
asks for httpx2 by name, and respx — which `TESTING.md` §1 used to name for
mocking — supports neither httpx2 nor Python 3.15. HTTP is mocked with
`httpx2.MockTransport`, which ships in the client and so cannot fall behind
it.

**BFF** — Node 26 · Fastify 5 · TypeScript strict · TypeBox · **Drizzle ORM**
(`ui` schema only; `crawl` is read-only and introspected — ADR-0021)

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

Every command is a `make` target. All of them run in Docker except
`make agents` and `make hooks`, which are plain host commands on purpose —
they have to work from any tool's terminal before the images exist.

```sh
make up            # start edge, db, api, worker, render, bff, web
make down          # stop, keep volumes
make reset         # stop and DROP the database volume
make logs          # follow all services
make shell-api     # shell inside the api container
make shell-bff
make psql          # psql into the dev database (both schemas)

make hooks         # wire .githooks/ — run once per clone
make migrate       # both chains: alembic (crawl) + drizzle (ui)
make revision m="add asset_queue"   # autogenerate a crawl migration
make revision-ui m="add schedules"  # generate a ui migration (drizzle-kit)
make drizzle-pull  # re-introspect crawl → crawl.generated.ts

make test          # everything
make test-api      # pytest
make test-bff      # the BFF suite
make test-web      # vitest
make e2e           # Playwright against the running stack

make lint          # ruff + mypy + eslint + prettier --check
make fmt           # ruff format + prettier --write
make types         # regenerate BOTH frontend API schemas from OpenAPI
make agents        # docs/agents/ → claude · cursor · opencode · antigravity
make generated     # types + drizzle-pull + agents. check fails on any diff

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
       http/        # HttpxFetcher, RenderServiceFetcher (HTTP to the sidecar)
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
     db/
       schema/      # ui.ts (Drizzle) · crawl.generated.ts (GENERATED — never edit)
  drizzle/         # generated migrations. generate + migrate, never push
  tests/
render/                    # Playwright behind HTTP (spec 012)
  src/
  tests/
frontend/
  src/
     api/           # generated types + typed client. Do not hand-edit types.
                    #   schema.crawler.d.ts · schema.ui.d.ts
     components/    # design-system components; one per DESIGN_SYSTEM.md entry
     views/         # one per screen in docs/SCREENS.md (the registry)
     hooks/
     lib/
     styles/        # theme.css → imports tokens + tailwind-theme
  tests/
docs/
  agents/          # agent roles — CANONICAL. Edit here, then `make agents`
design/            # tokens, logo, mockups. Read-only reference; the mockups
                    #   are NOT authoritative for layout (ADR-0031).
docker/            # Dockerfiles + Caddyfile
scripts/
  gen-agents.py    # docs/agents/ → the four tool formats. Stdlib only
.claude/ .cursor/ .opencode/ .agents/
                    # GENERATED agent definitions, one set per tool
.githooks/         # pre-commit · commit-msg · pre-push. `make hooks` wires them
.tasks/            # one handoff file per branch (ADR-0022)
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
- Comments explain _why_, never _what_. If you need a comment to say what the
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
- [ ] `make generated` produces no diff, and no generated file was hand-edited.
- [ ] It is on a branch, reviewed by an agent that did not write it, and the
      task file's handoff log is current (`docs/WORKFLOW.md`).
- [ ] If it touched the UI, it matches its Figma frame (node id in
      `docs/SCREENS.md`), covers every state `docs/UI_STATES.md` requires of
      it, and works in both themes.
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
