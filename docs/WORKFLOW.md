# Workflow — branches, gates and the agent team

How a change gets from an idea to `develop`. Read with
[`../AGENTS.md`](../AGENTS.md) (the rules) and
[`BUILD_PLAN.md`](BUILD_PLAN.md) (what to build next).

Decisions behind this: [ADR-0022](adr/0022-agent-team.md).

---

## 1. Branches

**`develop` is the integration branch** — that is what the repository
actually has, and nothing lands on it except a reviewed, green PR. `main` is
unused for now; if a release branch is ever wanted, it branches from
`develop`, not the other way round.

There is no remote yet. Everything below works on a local clone; when a remote
is added, the only change is that the PR becomes a real one instead of a
`git diff develop...HEAD` a human reads.

```
type/NN-slug          phase/task number + what it does
```

| Prefix   | For                         | Example                          |
| -------- | --------------------------- | -------------------------------- |
| `feat/`  | a build-plan task           | `feat/1.8-postgres-frontier`     |
| `fix/`   | a defect                    | `fix/sse-buffering-through-edge` |
| `chore/` | tooling, deps, CI           | `chore/0.2-makefile`             |
| `docs/`  | docs and ADRs only          | `docs/adr-0023-asset-dedupe`     |
| `spike/` | throwaway. **Never merged** | `spike/drizzle-crawl-introspect` |

**One build-plan task per branch.** If a task turns out to be three tasks, it
was three tasks — split it and say so in the PR rather than growing the branch.

**Commits:** imperative subject under 72 characters, body explaining _why_ when
the change is not obvious. Reference the task: `feat: claim query with SKIP
LOCKED (1.5)`.

## 2. The two gates

A full build on every commit is too slow to live with, and no gate at all is
how `develop` breaks. So the work is split by how long it takes:

| Gate           | Runs         | Time budget | What it does                                                      |
| -------------- | ------------ | ----------- | ----------------------------------------------------------------- |
| **pre-commit** | every commit | **< 10 s**  | format staged files, lint them, typecheck the changed package     |
| **pre-push**   | every push   | < 3 min     | `make check` — lint, types, the full suite, generated-file drift  |
| **CI**         | every PR     | —           | `make check` again, on a clean checkout, plus `make migrate-down` |

CI repeats pre-push deliberately. A hook can be skipped; CI cannot, and the
hook exists to save you the round trip, not to be the authority.

```sh
make hooks            # git config core.hooksPath .githooks — run once per clone
```

Hooks live in `.githooks/`, committed, so every clone and every agent gets the
same gate. `core.hooksPath` is one command instead of a dependency on Husky.

**`--no-verify` is allowed and must be declared.** There are real reasons to
bypass a hook — a WIP commit on a spike, a broken toolchain mid-upgrade. There
is no reason to do it silently, so say so in the PR body. An agent that uses
`--no-verify` without saying so has broken the contract in ADR-0022 §3.

### What pre-commit actually runs

```
staged *.py             → ruff format --fix, ruff check
staged *.ts/*.tsx       → prettier --write, eslint --fix
staged *.{md,json,yaml} → prettier --write
any *.ts/*.tsx staged   → tsc --noEmit on that package
any *.py staged         → mypy on changed files only
always                  → reject drizzle-kit push, secrets, .env, > 2 MB files
```

Formatters run with `--fix`/`--write` and **re-stage what they changed**, so a
formatting-only failure never blocks a commit — it fixes it. Lint errors that
need judgement do block.

### What pre-commit does _not_ run

Tests, Docker builds, `make check`. "Ensure the code is buildable before
commit" is the right instinct aimed at the wrong hook: a typecheck catches
nearly everything a build would, in a tenth of the time, and the actual build
runs on pre-push where a three-minute wait is acceptable.

## 3. The agent team

Eight specialists, defined once in [`agents/`](agents/) and generated into
whichever tool you are using. The division is by **phase of work**, not by
technology, because the handoff is what needs structure
([ADR-0022](adr/0022-agent-team.md)).

### Any tool, one definition

The roles describe how work moves through this repository. That is not a
property of the editor, so the definitions are not either.

```
docs/agents/*.md          ← edit here. Plain Markdown, no vendor frontmatter
      │
      make agents
      ├──→ .claude/agents/<name>.md      Claude Code
      ├──→ .opencode/agents/<name>.md    OpenCode v2
      ├──→ .cursor/rules/<name>.mdc      Cursor
      └──→ .agents/rules/<name>.md       Antigravity
```

`make check` fails if a generated copy is stale — the same rule that governs
the generated API types. **Never edit a generated copy**; the pre-commit hook
rejects it.

**`AGENTS.md` is the anchor.** It is the one file all four tools read without
configuration, so the hard rules live there and the roles point back to it.
Whatever you are driving, start by reading it.

Two differences between tools that are worth knowing rather than discovering:

- **No role pins a model.** Each tool uses its own default; the model is a
  per-session choice, not a property of the role.
- **How much a tool enforces differs.** Claude Code takes a tool allowlist;
  OpenCode v2 takes ordered `permissions` rules and is the strictest of the
  four, covering the shell as well as the filesystem. Cursor and Antigravity
  have no per-role restriction, so there `read-only` is prose. This matters
  most for `spydra-reviewer`, whose value is that it reports findings rather
  than quietly fixing them. Full table in
  [`agents/README.md`](agents/README.md).

**The gate lives in git, not in a tool.** `.githooks/` runs for every tool and
every clone. A tool's own hooks — the Claude Code `PreToolUse` guard on
generated files, for instance — catch a mistake earlier, but nothing depends
on them.

| Agent               | Owns                                                                     | Hands off to |
| ------------------- | ------------------------------------------------------------------------ | ------------ |
| `spydra-planner`    | reading the spec, writing `.tasks/<branch>.md`, declaring file ownership | implementer  |
| `spydra-backend`    | Python — domain, ports, adapters, scheduler, API                         | test-writer  |
| `spydra-bff`        | Fastify, Drizzle, the `ui` schema                                        | test-writer  |
| `spydra-frontend`   | React, components, screens, matching the mockups                         | test-writer  |
| `spydra-test`       | tests that fail without the change; fixtures; no production code         | reviewer     |
| `spydra-reviewer`   | the diff against the spec and the ADRs. **Read-only**                    | integrator   |
| `spydra-integrator` | `make check`, the PR, conflict resolution                                | the human    |
| `spydra-ops`        | Docker, compose, the Makefile, Caddyfile, hooks, CI, deps                | test-writer  |

### The slice

```
1  planner      reads BUILD_PLAN + the spec, writes .tasks/<branch>.md,
                declares the files this slice owns, opens the branch
2  implementer  (backend | bff | frontend) writes production code only
3  test         writes tests from the spec's acceptance criteria,
                WITHOUT reading the implementation conversation
4  reviewer     reads the diff, the spec and the relevant ADR. Read-only
5  integrator   make check, opens the PR, hands the number to the human
```

**Steps 3 and 4 are deliberately starved of context.** A test written from the
implementation tests what the code does; a test written from the acceptance
criteria tests what it should do. The difference only shows up when the code is
wrong, which is the only time it matters.

### Running them in parallel

Only across slices with **disjoint file sets**, declared in the task files
before either starts. Two slices that both want `spydra/scheduler/` are two
sequential slices.

```
# safe — different packages, no shared files
feat/3.10-domains-screen      (frontend)
feat/3.5-bff-schedules      (bff)

# not safe — same directory
feat/1.8-postgres-frontier   (backend, spydra/scheduler/)
feat/1.9-politeness-gate     (backend, spydra/scheduler/)
```

Whatever your tool's concurrency limit is, it is not a target. The limit here
is disjoint file sets, and on this repository that is rarely more than three
or four.

### The task file

`.tasks/<branch>.md`, committed on the branch, updated by every agent that
touches it:

```markdown
# feat/1.8-postgres-frontier

**Task:** BUILD_PLAN 1.8 · **Spec:** specs/002-scheduler.md §1–3
**ADRs that constrain this:** 0002 (postgres as queue), 0008 (ports)

## Files this slice owns

- backend/spydra/ports/frontier.py
- backend/spydra/adapters/postgres/frontier.py
- backend/tests/adapters/test_frontier.py

## Acceptance (from the spec)

- [ ] Claim is one transaction; two workers never claim the same row
- [ ] An expired lease returns the row to `pending` and increments `attempts`
- [ ] Three attempts moves a row to `failed`

## Handoff log

- planner — contract above; `in_flight` column confirmed present (spec 001 §1)
- backend — port + adapter done. The lease sweep is a separate query, not
  a trigger; see the comment on why
- test — 11 tests. Two-worker concurrency test uses two real connections
- reviewer — one finding: the sweep needs an index. Fixed by backend, re-reviewed

## Open questions

- none
```

The handoff log is the part that earns its keep. It is what the next agent
reads instead of guessing, and what the human reads in the PR instead of
reconstructing the reasoning from the diff.

## 4. Pull requests

- Title: `feat: claim query with SKIP LOCKED (1.5)`
- Body: what changed, why, which acceptance criteria now pass, anything
  deliberately left out — and any `--no-verify` use.
- Link the task file.
- Tick the task in `BUILD_PLAN.md` **in the PR**, not afterwards.
- The human merges into `develop`. Agents do not merge their own work.

## 5. Where this does not apply

Phase 0 is scaffolding: mostly one slice, mostly sequential, nothing to
parallelise. Run it as one branch (`chore/phase-0-scaffold`) with the planner
and integrator roles and skip the ceremony.

The gate itself is built first — Makefile, hooks and agent definitions are
tasks `0.1`–`0.3` — so everything after that is gated normally even while the
services are still being scaffolded. The team shape starts paying for itself
at phase 1, when there is something to break.
