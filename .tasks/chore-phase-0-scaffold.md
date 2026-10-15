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
- [ ] `make check` is green — the single gate, the same command CI runs
- [ ] the frontend renders a page using a design token and the theme toggle
      works
- [ ] an SSE test endpoint streams through the edge **unbuffered**
- [ ] the BFF cannot write `crawl`: `INSERT INTO crawl.runs` from the BFF
      role is rejected by Postgres
- [ ] the three git hooks fire and pre-commit is under 10 s
- [ ] one slice has been through the full agent handoff (0.17)

Per-task rule: a box in `BUILD_PLAN.md` is ticked only when its own
definition of done holds, not when its code is written.

## Sequencing decisions (planner)

- 0.6 and 0.7 are *written* in order, but their proofs need the stack:
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

- planner    — task file, sequencing decisions above. Found 0.1/0.3 partial
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

## Open questions

- ADR-0023 (drizzle down-migrations) to be written and verified before 0.10
  starts: drizzle-kit has no downgrade command, ADR-0021 requires
  `make migrate-down` to work for the `ui` chain.
- CI (0.16) is written but cannot be demonstrated green until a remote
  exists. Its steps run locally via the same make targets; the limit is
  recorded, not hidden.
