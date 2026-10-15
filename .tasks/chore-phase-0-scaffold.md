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

## Open questions

- ADR-0023 (drizzle down-migrations) to be written and verified before 0.10
  starts: drizzle-kit has no downgrade command, ADR-0021 requires
  `make migrate-down` to work for the `ui` chain.
- CI (0.16) is written but cannot be demonstrated green until a remote
  exists. Its steps run locally via the same make targets; the limit is
  recorded, not hidden.
