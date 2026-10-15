#!/usr/bin/env bash
# SessionStart — one line of orientation, so an agent starts on the right branch
# with the right contract rather than discovering both three tool calls later.
set -uo pipefail
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
task=".tasks/${branch}.md"
echo "branch: ${branch}"
if [ -f "$task" ]; then
  echo "task file: ${task} — read it before editing anything."
elif [ "$branch" = "develop" ] || [ "$branch" = "main" ]; then
  echo "On main. Open a slice first: docs/WORKFLOW.md §1, or use the spydra-planner agent."
else
  echo "No task file for this branch. The planner has not run (docs/WORKFLOW.md §3)."
fi
