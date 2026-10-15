#!/usr/bin/env python3
"""
Generate per-tool agent definitions from the canonical roles in docs/agents/.

The roles are the product of ADR-0022 and must not depend on which coding tool
is in front of them this week. So docs/agents/*.md is the single source of
truth — plain Markdown, vendor-neutral frontmatter — and this script projects
it into whatever shape each tool expects.

  make agents        regenerate
  make check         regenerates and fails on a diff

Stdlib only, no dependencies: this has to run from any tool's terminal,
including ones that know nothing about this project's Python environment.

Usage:
  python3 scripts/gen-agents.py            # write
  python3 scripts/gen-agents.py --check    # exit 1 if anything would change
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "agents"

BANNER = (
    "GENERATED FILE — DO NOT EDIT.\n"
    "Source: docs/agents/{name}.md   Regenerate: make agents\n"
    "Edit the source; this copy is overwritten and `make check` fails on drift."
)

# Claude Code expresses access as a tool allowlist; OpenCode as ordered
# permission rules. Cursor and Antigravity have no per-role tool restriction,
# so there `read-only` is prose — a real difference in enforcement strength,
# documented rather than papered over (docs/agents/README.md).
CLAUDE_TOOLS = {
    "read-only": "Read, Grep, Glob, Bash",
    "read-write": "Read, Grep, Glob, Write, Edit, Bash",
}

# Repository rules that every role is subject to, expressed where a tool can
# enforce them. These mirror AGENTS.md rules 16 and 17 — the same things the
# pre-commit hook rejects, caught one step earlier.
GENERATED_PATHS = (
    ".claude/agents/*",
    ".cursor/rules/*",
    ".opencode/agents/*",
    ".agents/rules/*",
    "*crawl.generated.ts",
    "*schema.crawler.d.ts",
    "*schema.ui.d.ts",
)
FORBIDDEN_COMMANDS = ("drizzle-kit push*",)

# What a read-only role may still run. It needs the diff; it does not need a
# shell. `*` is denied first and these are the exceptions, because OpenCode
# resolves an ordered list and the last matching rule wins.
READONLY_SHELL = ("git diff*", "git log*", "git show*", "git status*")


class Role:
    def __init__(self, path: Path) -> None:
        raw = path.read_text()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        if not m:
            raise SystemExit(f"{path}: missing frontmatter")
        meta = {}
        for line in m.group(1).split("\n"):
            if ": " in line:
                k, v = line.split(": ", 1)
                meta[k.strip()] = v.strip()
        for key in ("name", "description", "access"):
            if key not in meta:
                raise SystemExit(f"{path}: frontmatter is missing '{key}'")
        if meta["access"] not in CLAUDE_TOOLS:
            raise SystemExit(f"{path}: access must be read-only or read-write")
        entry = meta.get("entrypoint", "false").lower()
        if entry not in ("true", "false"):
            raise SystemExit(f"{path}: entrypoint must be true or false")
        self.name = meta["name"]
        self.description = meta["description"]
        self.access = meta["access"]
        # Can a human start a session as this role, or is it only ever handed
        # work by another agent? Neutral concept; each tool expresses it, or
        # ignores it, in its own way.
        self.entrypoint = entry == "true"
        self.body = m.group(2).lstrip("\n")

    def banner(self, comment: str = "<!--", close: str = "-->") -> str:
        text = BANNER.format(name=self.name)
        return f"{comment}\n{text}\n{close}\n\n"


def claude(r: Role) -> tuple[Path, str]:
    return (
        ROOT / ".claude" / "agents" / f"{r.name}.md",
        "---\n"
        f"name: {r.name}\n"
        f"description: {r.description}\n"
        f"tools: {CLAUDE_TOOLS[r.access]}\n"
        "---\n\n" + r.banner() + r.body,
    )


def _rule(action: str, resource: str, effect: str) -> str:
    return f'  - action: {action}\n    resource: "{resource}"\n    effect: {effect}\n'


def opencode(r: Role) -> tuple[Path, str]:
    # OpenCode v2: `permissions` is an ORDERED list and the LAST matching rule
    # wins, so broad rules come first and exceptions after.
    # Actions are `edit` (covers write and patch) and `shell` — not `write`,
    # not `bash`.
    rules = ""
    if r.access == "read-only":
        rules += _rule("edit", "*", "deny")
        rules += _rule("shell", "*", "deny")
        for cmd in READONLY_SHELL:
            rules += _rule("shell", cmd, "allow")
    else:
        rules += _rule("edit", "*", "allow")
        for path in GENERATED_PATHS:
            rules += _rule("edit", path, "deny")
        for cmd in FORBIDDEN_COMMANDS:
            rules += _rule("shell", cmd, "deny")

    # `all` leaves the role selectable as the primary agent; `subagent` means
    # it can only be handed work. Defaults to `all` in OpenCode, so both are
    # written explicitly.
    mode = "all" if r.entrypoint else "subagent"

    return (
        ROOT / ".opencode" / "agents" / f"{r.name}.md",
        "---\n"
        f"description: {r.description}\n"
        f"mode: {mode}\n"
        "permissions:\n" + rules +
        "---\n\n" + r.banner() + r.body,
    )


def cursor(r: Role) -> tuple[Path, str]:
    # alwaysApply: false + a description is Cursor's "Apply Intelligently":
    # the agent reads the description and pulls the rule in when it fits.
    # Always-on would put eight role definitions in every chat.
    return (
        ROOT / ".cursor" / "rules" / f"{r.name}.mdc",
        "---\n"
        f"description: {r.description}\n"
        'globs: ""\n'
        "alwaysApply: false\n"
        "---\n\n" + r.banner() + r.body,
    )


def antigravity(r: Role) -> tuple[Path, str]:
    # trigger: model_decision — Antigravity injects only the path and
    # description up front and reads the body when the task matches, which is
    # exactly how a role definition should load. always_on would burn the
    # shared 20k-token budget on eight roles that are mostly irrelevant.
    return (
        ROOT / ".agents" / "rules" / f"{r.name}.md",
        "---\n"
        "trigger: model_decision\n"
        f"description: {r.description}\n"
        "---\n\n" + r.banner() + r.body,
    )


TARGETS = (claude, opencode, cursor, antigravity)


def main() -> int:
    check = "--check" in sys.argv
    # README.md documents the directory; it is not a role.
    sources = [p for p in sorted(SRC.glob("*.md")) if p.name != "README.md"]
    roles = [Role(p) for p in sources]
    if not roles:
        raise SystemExit(f"no roles found in {SRC}")

    names = [r.name for r in roles]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate role names in docs/agents/")
    for role, path in zip(roles, sources):
        if role.name != path.stem:
            raise SystemExit(
                f"{path}: frontmatter name '{role.name}' does not match the "
                f"filename. They are the same identifier."
            )

    drift: list[str] = []
    written = 0
    for role in roles:
        for target in TARGETS:
            path, content = target(role)
            current = path.read_text() if path.exists() else None
            if current == content:
                continue
            rel = path.relative_to(ROOT)
            if check:
                drift.append(f"  {rel} {'differs' if current else 'missing'}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                written += 1

    if check:
        if drift:
            print("Generated agent files are stale:", file=sys.stderr)
            print("\n".join(drift), file=sys.stderr)
            print("\nRun 'make agents' and commit the result.", file=sys.stderr)
            return 1
        print(f"agents: {len(roles)} roles × {len(TARGETS)} tools, all current")
        return 0

    print(f"agents: {len(roles)} roles → {len(TARGETS)} tools, {written} file(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
