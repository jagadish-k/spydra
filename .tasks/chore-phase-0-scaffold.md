# chore/phase-0-scaffold

**Task:** BUILD_PLAN Phase 0 (0.1–0.17) · **Spec:** specs/010-service-topology.md,
specs/012-render-sidecar.md · **ADRs that constrain this:** 0010 (docker-native),
0013 (generated types), 0015 (topology), 0016 (render sidecar), 0017 (versions),
0018 (React 19 + Tailwind 4), 0021 (Drizzle), 0022 (agent team)

Phase 0 runs as one branch, mostly sequential (WORKFLOW §5). The driving
session carries planner + integrator; package work goes to spydra-ops
(Docker/compose/Caddyfile/Makefile/CI), spydra-backend, spydra-bff,
spydra-frontend, spydra-test; spydra-reviewer runs before a task is called
done, clustered: after 0.4–0.5, 0.6–0.8+proofs, 0.9–0.10, 0.11–0.13,
0.14–0.16, and 0.17.

## Files this slice owns

Everything — this is the scaffold branch: `Makefile`, `docker/`,
`compose.yaml`, `backend/`, `bff/`, `render/`, `frontend/`, `.env.example`,
`.githooks/`, `scripts/`, `docs/BUILD_PLAN.md` (ticks), `docs/adr/0023-*`,
and the stale-note fix in `docs/adr/0013`.

Pre-existing on `develop` (verified current): `.gitignore`, `.githooks/*`,
`scripts/gen-agents.py`, all four generated adapter sets, `.claude/`,
`.cursor/`, `.opencode/`, `.agents/`.

## Acceptance (Phase 0 exit criteria, copied from BUILD_PLAN)

- [ ] `make up` gives a working stack reachable at `http://localhost:8080`
- [x] `make check` is green — the single gate, the same command CI runs
- [ ] the frontend renders a page using a design token and the theme toggle
      works
- [x] an SSE test endpoint streams through the edge **unbuffered**
      (6 events, gaps 1.00–1.01 s, asserted 2026-10-15)
- [x] the BFF cannot write `crawl`: `INSERT INTO crawl.runs` from the BFF
      role is rejected by Postgres (`permission denied for table runs`,
      fresh-volume boot, `make verify-grants`)
- [x] the three git hooks fire and pre-commit is under 10 s (0.9 s)
- [ ] one slice has been through the full agent handoff (0.17)

Per-task rule: a box in `BUILD_PLAN.md` is ticked only when its own
definition of done holds, not when its code is written.

## Sequencing decisions (planner)

- 0.6 and 0.7 are _written_ in order, but their proofs need the stack:
  unbuffered SSE needs a streaming origin (nothing emits until the API
  exists), and the grant proof needs a `crawl` table (none until 1.1).
  Both are proved right after 0.8, before anything depends on them.
- The SSE proof uses a temporary `GET /api/crawler/__smoke/sse` route on the
  API — one event per second. Scaffolding with an end date: deleted by
  task 3.6, the same pattern as the 1.12 YAML loader.
- The grant proof creates a throwaway `crawl.runs` table as `spydra_api`
  (the schema owner), then attempts `INSERT` as `spydra_bff`. That tests
  the grant, which is the boundary — not the phase-1 schema.
- BUILD_PLAN 0.12 says "assert `bg-red-500` fails the build". In Tailwind
  v4 an unknown utility in markup is silently not generated, not a build
  error (only `@apply` errors). The assertion becomes: `--color-*: initial`
  in `@theme` (structural) plus a test failing on any raw palette class in
  `frontend/src`. Same guarantee, honest mechanism.

## Handoff log

- planner — task file, sequencing decisions above. Found 0.1/0.3 partial
  work already on `develop` (hooks, gen-agents, adapters,
  .gitignore); verified `gen-agents.py --check` green. 0.2
  (Makefile) is the first real build task; 0.3 is wire+verify.
- integrator — 0.1–0.3 done. `make check` green on the empty project
  (skip-guards + agents drift check are the only live parts).
  Hooks wired via `make hooks`; verified: 119-char subject
  rejected, staged `.env` rejected, push to `develop` refused
  (temp bare remote, removed after). Feature-branch push ran
  `make check` under pre-push. Pre-commit timing: **0.9 s**
  (budget 10 s). 0.2/0.3 DoD held before ticking.
- ops — 0.4/0.5 via subagent: five Dockerfiles + compose + package
  manifests. Images: python:3.15-slim, node:26-slim,
  postgres:18, caddy:2-alpine, playwright v1.64.1-noble pinned
  to npm playwright@1.64.1, uv 0.13.1. Found+fixed two Makefile
  bugs (fmt-staged-js re-split, reset-deps volume rm), one
  postgres-18 reality (pgdata mounts at /var/lib/postgresql,
  not .../data — DEVELOPMENT sketch updated). ADR-0023 written
  BEFORE compose: sketch had render unreachable (alone on
  egress, no DNS) and any shared net breaks spec 012 isolation;
  resolution = host-loopback indirection + all inspection ports
  on 127.0.0.1. Verified live: from inside render, api:8000 →
  ENOTFOUND.
- backend — 0.8: FastAPI app factory (main.py) mounting /api/crawler;
  healthz (liveness-only, 200 with db:"down" when DB unreachable — spec 010
  §4 readiness arrives phase 3) via raw asyncpg SELECT 1 (asyncpg added,
  SQLAlchemy NOT — raw connection preferred, less surface; pyproject mypy
  override for asyncpg's missing types, no inline ignores); __smoke/sse
  1 event/s × 6 with the mandated deletion header. Ruff (E,F,I,UP,B;
  line 100; py315) + mypy strict clean in container. test_scaffold.py
  replaced by test_healthz.py + test_import_contracts.py (stdlib-AST
  domain→adapters walk; teeth proven: scratch file with 4 violation kinds
  failed all 4, then removed). Deviations: uv distroless image cannot
  execute (no shell/libc probe) — lock regenerated via `compose run api
uv lock`, same pinned uv 0.13.1; stale spydra_venv volume dropped
  (`make reset-deps`) before rebuild since it predated asyncpg; compose api
  command now the real uvicorn line. One bug found+fixed in-flight:
  `async with asyncpg.connect()` is invalid (plain coroutine) — explicit
  connect/close with suppressed close errors. Verified: build, curl
  healthz {"status":"ok","db":"ok"}, SSE 4 frames/4s via published port,
  ruff+mypy clean, pytest 2 passed/1 skipped (contract skips until
  spydra/domain exists by design).
- integrator — 0.7 PROVEN from a fresh volume boot with the real init file:
  BFF INSERT → "permission denied for table runs"; BFF SELECT
  allowed; api writing ui rejected. `make verify-grants` is the
  repeatable proof. import-linter dropped — grimp has no cp315
  manylinux aarch64 wheel (verified on PyPI; the domain→adapters
  contract moves to a stdlib-AST pytest in 0.8, which blocks CI
  where a lint only warns). `design/tokens/*` + `docs/
     UI_STATES.md` appeared in the tree mid-session — NOT this
  branch's work, left uncommitted for the human.

- integrator — 0.6 PROVEN: 6 SSE events through :8080, arrival gaps
  1.00–1.01 s (spec 010 §6 asserts on arrival times — streaming,
  not batched). 0.6/0.7/0.8 ticked; 0.8's "import-linter"
  wording satisfied by the AST pytest instead — grimp wheel
  evidence in pyproject comments.
- bff — 0.9: Fastify 5 skeleton (server.ts). GET /api/ui/healthz →
  {status:"ok", api:"ok"|"down"}; api = fetch of the api's healthz,
  2 s AbortSignal.timeout, liveness-only (200 with api:"down" while
  api stopped — verified, then api restarted). db field arrives with
  0.10 (comment in server.ts). TypeBox schema as the route's response
  schema — the wiring 0.9 exists for. OpenAPI: @fastify/swagger
  (spec) + @fastify/swagger-ui (UI split out since swagger v9) →
  /docs HTML + own /openapi.json route (plugin's json is /docs/json;
  DEVELOPMENT.md promises /openapi.json). Both reachable via :8080
  edge route. package.json: +fastify/@fastify/swagger/@fastify/
  swagger-ui/@sinclair/typebox; "type":"module" (NodeNext top-level
  await); lock regenerated in-container; image rebuilt (Dockerfile
  unchanged — npm ci covers it). tsconfig: +skipLibCheck (thread-
  stream's d.ts vs TS7, dep-only). Deviation: typescript-eslint
  CANNOT be added — TS 7 (Go port) has no JS API; tseslint peers
  <6.1.0 only and ERESOLVE blocks install (npm ci would fail).
  eslint stays empty-config on purpose (comment in eslint.config.mjs);
  tsc --noEmit + prettier cover src. All verified in-container.

- bff — 0.10: Drizzle wiring landed; **the chain is proven but BLOCKED on
  the dev db by docker/init-schemas.sql's shape — see deviation, needs an
  ops/integrator decision before 0.10 can be ticked.** Landed:
  drizzle.config.ts exactly per ADR-0021/DEVELOPMENT sketch (schemaFilter
  ['ui'] load-bearing, ledger at drizzle default drizzle.__drizzle_migrations
  per ADR-0024); ui.ts with throwaway ui.drizzle_probe; migration 0000
  generated via npx drizzle-kit generate (unmodified); hand-written
  0000_drizzle_probe.down.sql (DROP SCHEMA ui CASCADE — 0000 creates the
  schema, so its inverse removes it; dropping only the table breaks the
  migrate→down→migrate invariant because up re-hits CREATE SCHEMA);
  migrate-down.ts runner (journal-shape-validated, 42P01→nothing-to-rollback,
  one step back, deletes ledger row in the same tx); node:test guards —
  (a) every *.sql has sibling .down.sql, (b) nothing under bff/drizzle may
  mention crawl. or carry non-ui-qualified DDL (SQL comments stripped before
  the DDL scan). Teeth proven both ways (renamed down.sql → fail; appended
  CREATE TABLE crawl.evil → fail; both restored, file byte-identical to
  generated). Driver: postgres.js — ESM-native, zero-config pooling,
  drizzle's first-class pg pairing (node-postgres would drag CJS/pg-types
  heritage into an ESM-only package). healthz now {status, db, api} with
  db via postgres.js select 1, same never-fail convention; onClose ends the
  pool. +drizzle-orm, +postgres, +drizzle-kit (dev); lock regenerated
  in-container; image rebuilt; bff/.prettierignore excludes drizzle/ (kit
  output must reproduce byte-for-byte — formatting it would be hand-editing
  a generated artifact). tsc --noEmit + eslint + prettier clean; tsconfig
  include += tests.
- bff — 0.10 DEVIATION (the blocker, fully diagnosed): `make migrate-ui`
  CANNOT work against the dev db as init-schemas.sql shapes it, and no
  grant fixes it. Three independent facts, each verified live: (1)
  drizzle-kit migrate unconditionally runs `CREATE SCHEMA IF NOT EXISTS
<ledger-schema>` (drizzle-orm pg-core/dialect.js:54) — as spydra_bff that
  is `permission denied for database spydra` (role has CREATE on schema ui
  only; PG-18 checks db CREATE even when the schema exists — drizzle-kit
  swallows the error, silent exit 1); (2) generated migration 0000 contains
  `CREATE SCHEMA "ui";` (plain, no IF NOT EXISTS — first generate always
  emits it for pgSchema schemas) which collides with init's pre-created ui:
  ERROR 42P06 even as superuser; (3) alembic survives the same shape only
  because it never emits CREATE SCHEMA and its version table lives in the
  granted schema. The proof was therefore run on a scratch database
  encoding the RECOMMENDED fix: no pre-existing ui, GRANT CREATE ON
  DATABASE to spydra_bff. Full cycle green as spydra_bff: migrate →
  ui.drizzle_probe created + ledger 1 → migrate:down → table+schema+ledger
  row gone → migrate again → recreated. `make migrate-down` green on the
  real db today (alembic skip message + runner nothing-to-roll-back).
  RECOMMENDED (one file, ops-owned): in docker/init-schemas.sql replace
  `CREATE SCHEMA ui; GRANT USAGE, CREATE ON SCHEMA ui TO spydra_bff;` with
  `GRANT CREATE ON DATABASE spydra TO spydra_bff;` — migration 0000 then
  creates AND OWNS ui (single owner; the crawl grants stay untouched, so
  the 010 §3 boundary is unchanged — db-CREATE lets the role create new
  schemas, not touch crawl tables). Alternative rejected: blessing removal
  of the CREATE SCHEMA line from generated 0000 (hand-editing an artifact
  ADR-0021 exists to keep pristine, and every fresh generate re-adds it).
  After ops lands the init change: `make reset && make migrate-ui` must be
  re-proven on the real db, then 0.10 can tick. Dev-db evidence left
  pristine: runtime grant revoked, stray ui.__drizzle_migrations dropped,
  scratch db deleted.

- ops — 0.11 render sidecar. Plain ESM node:http (zero new npm deps —
  two routes don't justify express; body parsing hand-rolled with the
  64 KB cap enforced while reading). src/: limits.js (caps + truncate),
  validate.js (422 matrix + 30 s clamp), context-queue.js (cap with
  injectable timers), index.js (server, one browser, ref-counted entries,
  retire-between-requests so recycle drains in-flight contexts). Dockerfile
  placeholder → real CMD; pin pairing untouched. compose untouched —
  /healthz shape matches the existing healthcheck. Tests: node --test,
  no browser, mock.timers for the 5 s queue window — 17/17 in container.
  Live-verified: healthz exact spec shape (contexts_max 3, browser_version
  156.0.8078.4); example.com render 200 with full contract; 422s (bad
  URL/protocol/wait_until/timeout_ms), 400 bad JSON, 413 >64 KB;
  **503 proven live** — 3 holders via never-matching wait_for_selector
  (15 s), 4th queued exactly 5.015 s then 503, holders returned 504 (=
  timeout classification proven too); ADR-0023 re-check: api:8000 and
  db:5432 from inside render → ENOTFOUND. Integration gaps stated:
  alert() auto-dismiss wired but not live-proven (no fixture page that
  dialogs); 10 MB truncation is unit-proven only; recycle path
  (500 pages/30 min) is code-reviewed but not waited out. Note: the
  playwright:v1.64.1-noble image ships **Node 24.21**, not 26 —
  AGENTS.md/010 say "Node 26"; reality wins unless ops re-pins (did not:
  the playwright pin pairing is load-bearing). BUILD_PLAN 0.11 tick left
  to integrator after review.

## Open questions

- ADR-0023 (drizzle down-migrations) to be written and verified before 0.10
  starts: drizzle-kit has no downgrade command, ADR-0021 requires
  `make migrate-down` to work for the `ui` chain.
- CI (0.16) is written but cannot be demonstrated green until a remote
  exists. Its steps run locally via the same make targets; the limit is
  recorded, not hidden.
