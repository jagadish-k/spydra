#!/usr/bin/env bash
# PreToolUse(Edit|Write) — refuse edits to generated files.
#
# AGENTS.md rule 16: generated files are build artifacts that happen to be
# committed. Hand-editing one to make the build pass inverts the point of
# generating it, and the failure is silent until the next regeneration.
set -uo pipefail
path=$(jq -r '.tool_input.file_path // .tool_input.path // empty')
[ -z "$path" ] && exit 0

case "$path" in
  *schema.crawler.d.ts|*schema.ui.d.ts|*crawl.generated.ts)
    echo "Refusing to edit $path — it is generated. Run 'make generated' instead (AGENTS.md rule 16, ADR-0013, ADR-0021). If the generator produces the wrong output, fix the schema or the spec, not the artifact." >&2
    exit 2 ;;
  */.claude/agents/*|*/.cursor/rules/*|*/.opencode/agents/*|*/.agents/rules/*)
    echo "Refusing to edit $path — agent definitions are generated from docs/agents/ (ADR-0022 §6). Edit the canonical role there and run 'make agents'; this copy is overwritten." >&2
    exit 2 ;;
esac
exit 0
