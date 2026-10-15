# Agent roles — the canonical definitions

**This directory is the source of truth.** Everything under `.claude/`,
`.cursor/`, `.opencode/` and `.agents/rules/` is generated from here by
`make agents` and overwritten without warning.

The roles are a product of [ADR-0022](../adr/0022-agent-team.md). They
describe _how work moves through this repository_ — who plans, who writes,
who tests, who reviews, who integrates. That does not depend on which coding
tool is in front of them this week, so the definitions do not either.

## The format

Plain Markdown. The frontmatter has four keys and none of them are
vendor-specific:

```markdown
---
name: spydra-backend
description: One or two sentences. This is what a tool shows its model when
  deciding whether to load the role, so it must say when to use it, not just
  what it is.
access: read-write # read-only | read-write
entrypoint: false # can a human start a session as this role?
---

The body is the role's instructions. It becomes the system prompt where the
tool supports that, and an on-demand rule where it does not.
```

- **`name`** — also the generated filename. Prefix with `spydra-` so the roles
  are distinguishable from whatever else a tool has loaded.
- **`description`** — the routing signal. Every one of the four tools decides
  whether to pull a role in based on this string, so write it as _when to use
  this_, not as a title.
- **`access`** — `read-only` or `read-write`. See the enforcement table below.
- **`entrypoint`** — true for the roles a human plausibly _starts_ with
  (planner, integrator, ops); false for the ones that are only ever handed
  work. Defaults to false. OpenCode expresses it as `mode: all` versus
  `mode: subagent`; the other tools have no equivalent and ignore it.

## Adding or changing a role

1. Edit or add the file here.
2. `make agents`.
3. Commit both. `make check` fails if the generated copies are stale.

Never edit a generated copy. The banner says so, the next `make agents` would
throw the change away, and the pre-commit hook rejects an adapter staged
**without** a matching change to `docs/agents/` — which is exactly the
hand-edit case. Staging the pair together is the normal workflow and passes,
provided the two agree.

## Where they are generated to

| Tool        | Path                         | Loading                                                                        |
| ----------- | ---------------------------- | ------------------------------------------------------------------------------ |
| Claude Code | `.claude/agents/<name>.md`   | subagent; body is the system prompt                                            |
| OpenCode v2 | `.opencode/agents/<name>.md` | `mode` + `permissions`; body is the system prompt                              |
| Cursor      | `.cursor/rules/<name>.mdc`   | `alwaysApply: false` + description — "apply intelligently"                     |
| Antigravity | `.agents/rules/<name>.md`    | `trigger: model_decision` — path and description injected, body read on demand |

Cursor and Antigravity load by description rather than always-on, deliberately:
eight role definitions in every turn would crowd out the actual task, and
Antigravity's always-on budget is shared across all rules.

## How much of this a tool actually enforces

|                             | Claude Code       | OpenCode v2         | Cursor     | Antigravity |
| --------------------------- | ----------------- | ------------------- | ---------- | ----------- |
| `access: read-only`         | tool allowlist    | `permissions` rules | prose      | prose       |
| No edits to generated files | `PreToolUse` hook | `permissions` rules | prose      | prose       |
| `drizzle-kit push` refused  | pre-commit hook   | `permissions` rules | pre-commit | pre-commit  |
| `entrypoint`                | n/a               | `mode`              | n/a        | n/a         |

**OpenCode v2 is the strictest of the four**, because its permission model
covers both the filesystem and the shell. The generator emits an ordered rule
list — broad rule first, exceptions after, since the last matching rule
wins — so the reviewer gets `edit: deny` and `shell: deny` with `git diff`,
`log`, `show` and `status` allowed back, plus the read-only pipe partners
(`head`, `tail`, `wc`, `grep`, `cat`, `ls`, …): the scanner denies a compound
command whole when any segment is denied, so a bare `git diff*` allow dies
the moment a reviewer writes `git diff | head` (found during the 0.17 slice).
It has what it needs to review and nothing it needs to write.

Read-write roles get the repository's own rules as permissions: no edits to
any generated file, and `drizzle-kit push` refused outright (AGENTS.md rules
16 and 17). The pre-commit hook already rejects both; this catches them one
step earlier, before the edit happens.

**On Cursor and Antigravity, `read-only` is prose** — forceful prose at the
top of the role, but prose. Neither has per-role tool restriction today. That
is a real difference and it is written down rather than glossed over. It
matters most for `spydra-reviewer`, whose whole value is reporting findings
instead of quietly fixing them.

The backstop, on every tool, is the one that catches everything else here:
the diff, and the gate (`docs/WORKFLOW.md` §2). Nothing load-bearing depends
on a vendor's permission model being present.
