# Slice task files

One file per branch: `.tasks/<branch>.md`, committed on that branch.

It is the handoff artifact between agents (ADR-0022 §2). A subagent starts
with a fresh context and only the task message written for it — nothing in
the previous agent's head reaches the next one, so anything that matters is
written here or it is lost.

Template and rules: [`../docs/WORKFLOW.md`](../docs/WORKFLOW.md) §3.
