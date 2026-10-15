# ADR-0022 — Specialised agents, sequential within a slice

**Status:** accepted
**Date:** 2026-10-15
**Context:** phase 0 onward · affects `docs/WORKFLOW.md`, `.claude/`

---

## Context

This repository will be built largely by AI agents. The appealing shape is
many agents working at once — more parallelism, more throughput.

Applied naively to one codebase it produces three failures, and they compound:

1. **Merge conflict as the normal case.** Two agents editing
   `backend/spydra/scheduler/` at the same time do not merge cleanly, and
   neither has the context to resolve the other's intent.
2. **Convention drift.** Each agent starts with a fresh context window. Left
   to themselves, three agents produce three error-handling styles, three
   naming schemes and three test layouts in one afternoon.
3. **Unverified handoff.** Agent A says "done". Agent B believes it. Nothing
   checked. This is the expensive one, because it surfaces three agents later.

The constraint that decides the design: **a subagent starts with a fresh
context and only the task message written for it.** Nothing in the first
agent's head reaches the second. Any handoff that depends on remembering is
already broken.

## Decision

### 1. Specialise sequentially within a slice. Parallelise only across slices.

A **slice** is one vertical change with an owner and a branch — "the claim
query", "the seeds screen". Within a slice, agents run in sequence and each
one's output is the next one's input:

```
plan → implement → test → review → integrate
```

Across slices, agents run in parallel **only when their file sets are
disjoint**, declared up front in the branch's task file. Two slices that both
want `spydra/scheduler/` are not parallel; they are two sequential slices.

### 2. The handoff artifact is a file in the repository

Every slice carries `.tasks/<branch>.md`, committed on the branch: the
contract, the files owned, what the previous agent did, what remains, and the
open questions. An agent's first action is to read it; its last is to update
it.

Conversation state is not a handoff. The artifact is reviewable in the PR,
survives a crashed session, and makes a resumed slice indistinguishable from a
fresh one.

### 3. `make check` is the contract, not a claim

No agent accepts a handoff on the word of the last one. A slice is passed on
when `make check` passes, and a `Stop` hook runs it rather than trusting the
agent to.

"Done" means the gate passed. There is no other definition.

### 4. The reviewer never wrote the code

Review runs as a separate agent with a fresh context, given the diff and the
spec, **not** the implementation conversation. An agent reviewing its own work
re-reads its own reasoning and finds it convincing, which is the one thing a
review exists to prevent.

For anything touching politeness, the queue or the schema, the reviewer reads
the ADR rather than the implementation.

### 5. One writer per file, always

File ownership is declared in the task file before work starts. An agent that
needs a file it does not own stops and says so; it does not edit and hope.
This is the rule that makes parallel slices safe, and it is cheap to follow
because the declaration is already required.

### 6. The roles are tool-neutral; the adapters are generated

The roles describe how work moves through this repository. That is not a
property of whichever coding tool is in front of them this week, and this
project will see several — Claude Code, Cursor, OpenCode and Antigravity are
all in use.

So the definitions live in **`docs/agents/*.md`**: plain Markdown with three
vendor-neutral frontmatter keys (`name`, `description`, `access`).
`make agents` projects them into each tool's shape, and `make check` fails on
drift — the same rule that already governs generated API types (ADR-0013) and
`crawl.generated.ts` (ADR-0021).

| Tool        | Generated to                 | Loading                                           |
| ----------- | ---------------------------- | ------------------------------------------------- |
| Claude Code | `.claude/agents/<name>.md`   | subagent; body is the system prompt               |
| OpenCode v2 | `.opencode/agents/<name>.md` | `mode` + `permissions`; body is the system prompt |
| Cursor      | `.cursor/rules/<name>.mdc`   | `alwaysApply: false` + description                |
| Antigravity | `.agents/rules/<name>.md`    | `trigger: model_decision`                         |

**`AGENTS.md` is the anchor**, because it is the one file every one of these
tools reads without configuration. The hard rules live there; the roles point
back to it.

Three consequences worth stating plainly:

- **No model is pinned in a role.** Model names are the most tool-specific
  and shortest-lived thing that could go in these files. Each tool uses its
  own default, and the choice of model is a per-session decision rather than
  a property of the role.
- **`access: read-only` is hard-enforced on Claude Code and OpenCode v2**,
  which take a tool allowlist and an ordered permission list respectively.
  OpenCode is the strictest of the four: its model covers the shell as well
  as the filesystem, so the reviewer gets `edit: deny`, `shell: deny`, and
  `git diff`/`log`/`show`/`status` allowed back — everything it needs to
  review and nothing it needs to write. **Caveat found by the 0.17 slice:**
  the OpenCode runtime, as of phase 0, does not honor resource-level
  allow-backs under a denied `shell` action for commands touching a path
  (verified with probe agents; documented in `docs/agents/README.md`). The
  generated rules are still correct per the docs, but the reviewer role
  carries the real mechanism: when shell is unavailable the integrator
  pastes the diff into the task message, and the reviewer verifies by
  direct reads. On Cursor and Antigravity it is
  prose. That is a genuine difference in enforcement strength and it matters
  most for the reviewer; the backstop everywhere is the same as for
  everything else here — the diff, and the gate.
- **Repository rules are expressed as permissions where a tool can hold
  them.** No edits to generated files, and `drizzle-kit push` refused
  (rules 14 and 15). The pre-commit hook already rejects both; a permission
  rule catches them before the edit rather than before the commit.
- **The gate is in git, not in a tool.** `.githooks/` runs for every tool and
  every clone. Anything a tool's own hook system does — the Claude Code
  `PreToolUse` guard on generated files, say — is a convenience that catches
  the mistake earlier, never the thing being relied on.

## Consequences

**What this costs.** Less parallelism than the "army" framing suggests. Five
agents on five slices, not fifteen on one. The task file is overhead on every
slice, including the trivial ones.

**What it buys.** Handoffs that are verified rather than trusted, a review
that is not self-review, and conflicts that are prevented by declaration
instead of resolved after the fact.

**The honest limit.** The bottleneck on this project is a human reviewing
templates (`BUILD_PLAN.md` § Known risks), and it stays a human reviewing
templates. Agents make the code arrive faster. They do not move the number
that matters, and a design that pretended otherwise would be the same mistake
this project is built to avoid.

## Alternatives rejected

| Option                                 | Why not                                                                                                 |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Many agents on one branch              | Conflicts and drift; nobody owns the result                                                             |
| One generalist agent for everything    | No separation between author and reviewer, which is the whole point of §4                               |
| Handoff by conversation summary        | A subagent gets a fresh context — the summary is the only thing that survives, and it is unverifiable   |
| Roles written natively per tool        | Four copies of eight roles, drifting from the day they are written                                      |
| Roles only in `AGENTS.md`              | One file cannot hold eight roles without being loaded whole, every turn, by every tool                  |
| Pinning a model per role               | The shortest-lived, most tool-specific thing that could go in a vendor-neutral file                     |
| Lowest-common-denominator adapters     | Leaves OpenCode's permission model unused — the one place a role's `read-only` can actually be enforced |
| Agent-written git history (auto-merge) | A PR nobody read is not review; `develop` stays protected                                               |
