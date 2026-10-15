# Starter prompt — phase 0

Paste the block below into a fresh session of whichever tool you are using —
Claude Code, Cursor, OpenCode or Antigravity — opened at
`~/projects/personal/spydra`. Nothing else is needed; everything it refers to
is in the repository.

The roles live in `docs/agents/` and are projected into each tool's format
from there.

Keep this file. When phase 1 starts, the prompt is the same shape with a
different phase number and a different exit criterion.

## Starting it in each tool

The prompt itself is identical everywhere — it refers to roles and files, not
to any product's features. Only the way you open the session differs.

| Tool | Open it | Roles come from |
| --- | --- | --- |
| **OpenCode v2** | `cd ~/projects/personal/spydra && opencode`, then paste the block. Or `opencode run "$(sed -n '/^```$/,/^```$/p' docs/PHASE0_PROMPT.md)"` if you prefer non-interactive | `.opencode/agents/*.md` — `mode: subagent`, with ordered `permissions`. Invoke one by name (`@spydra-ops`); `spydra-reviewer` is genuinely blocked from writing |
| **Claude Code** | `claude` in the repo root, paste the block | `.claude/agents/*.md` — subagents with a tool allowlist |
| **Cursor** | open the folder, paste into the agent pane | `.cursor/rules/*.mdc` — `alwaysApply: false`; attach the rule or name the role |
| **Antigravity** | open the folder, paste into the agent pane | `.agents/rules/*.md` — `trigger: model_decision` |

All four read `AGENTS.md` without configuration, which is why the hard rules
live there.

**OpenCode v2 is the strictest of the four.** Its `permissions` are an
ordered array where the last matching rule wins, and they cover the shell as
well as the filesystem — so `spydra-reviewer` can run `git diff` and nothing
else, and `drizzle-kit push` is denied at the tool layer rather than by
convention. Cursor and Antigravity have no per-role restriction, so there
`read-only` is prose the model can ignore. If you want the reviewer's
read-only property actually enforced, run that step from OpenCode or Claude
Code.

**Run `make agents` once per clone** (or `python3 scripts/gen-agents.py`
before the Makefile exists) so your tool's directory is populated. The
adapters are committed, so normally they are already there; `make check`
fails if they have drifted from `docs/agents/`.

---

```
We are starting Phase 0 of Spydra. The design and handoff package are
finished and committed; there is no application code yet.

Read these first, in this order, and do not skip any:
  1. AGENTS.md                      — the hard rules, stack, commands
  2. docs/WORKFLOW.md               — branches, the two gates, the agent team
  3. docs/BUILD_PLAN.md § Phase 0   — the tasks and the exit criteria
  4. docs/DEVELOPMENT.md            — compose topology and the five details
                                      that are not optional
  5. docs/specs/010-service-topology.md  — six services, routing, who owns
                                           which data

Then read the ADRs those name, at minimum 0010 (docker-native), 0013
(generated types), 0015 (service topology), 0016 (render sidecar), 0017
(version policy), 0018 (React 19 + Tailwind 4), 0021 (Drizzle) and 0022
(the agent team).

Work on one branch: chore/phase-0-scaffold. Phase 0 is scaffolding, so run it
mostly sequentially rather than fanning out — there is nothing to parallelise
yet. Build tasks 0.1–0.3 first and in order: they are the Makefile, the hooks
and the agent definitions, they have no dependencies, and once they exist
every later commit is gated normally.

The roles are defined in docs/agents/ and generated into this tool's format by
`make agents`: use spydra-ops for Docker, the Makefile, the Caddyfile, CI and
the hooks;
spydra-backend, spydra-bff and spydra-frontend for their packages;
spydra-test for tests; spydra-reviewer before you consider a task done. If
this tool has no subagent mechanism, read the role file yourself before
starting that part of the work — the roles are plain Markdown and work as
instructions either way.

Start by writing .tasks/chore-phase-0-scaffold.md using the template in
WORKFLOW §3, with the Phase 0 exit criteria copied from BUILD_PLAN.md. Then
work the tasks top to bottom, ticking each in BUILD_PLAN.md as its definition
of done actually holds.

Five things I care about more than speed:

  - 0.1 to 0.3 before anything else, in order. The gate has to exist before
    the work it gates, otherwise the first third of this phase lands ungated
    and you discover the formatting and lint rules afterwards.
  - Task 0.6 and 0.7 before anything that depends on them. Buffered SSE
    presents as a frontend bug and a missing grant presents as nothing at
    all. Prove both: an SSE endpoint streaming unbuffered through the edge,
    and `INSERT INTO crawl.runs` from the BFF role being rejected by
    Postgres.
  - `make check` must be the single gate, and the same command CI runs.
    Green locally means green in CI because they are the same command in the
    same images.
  - The hooks must actually fire. Verify a long commit subject is rejected, a
    staged .env is rejected, and a push to develop is refused. These are git
    hooks on purpose — they have to work from every tool, not just this one.
  - Finish with task 0.17 — one trivial slice through the full agent handoff.
    The point is to find out whether the handoff works while the stakes are a
    hello-world.

Before you write anything, tell me: the task order you intend, anything in
Phase 0 you think is wrong or missing, and any decision you hit that no ADR
covers. If a task needs a decision that is not in docs/adr/, stop and write
the ADR first — that is rule 1 of how this repository works, not a formality.
```

---

## Why the prompt is shaped this way

**It names the reading order rather than saying "read the docs".** An agent
given a directory reads the first three files and starts typing. The order
above is the dependency order: rules, then workflow, then what to build, then
how to run it.

**It says what to do first and what to prove.** "Scaffold phase 0" is a
200-line Makefile and a shrug. "Prove SSE streams unbuffered and the BFF
cannot write `crawl`" is a test that either passes or does not.

**It asks for pushback before the first file.** The most expensive failure in
a scaffolding session is an agent confidently building the wrong shape for an
hour. The last paragraph costs one round trip and is the cheapest insurance
available.

**It does not list the tasks.** They are in `BUILD_PLAN.md`, which is the
thing that gets ticked. A prompt that restates them creates a second source
of truth that drifts within the first hour.

**It names no tool and no model.** The repository is driven from Claude Code,
Cursor, OpenCode or Antigravity as suits the task, so the prompt refers to
roles rather than to a product's features, and leaves the model to whatever
the session is already using.
