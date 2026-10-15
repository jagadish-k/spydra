# 0001 — Record architecture decisions

**Status:** Accepted · 2026-10-15

## Context

This system is built mostly by agents, across sessions that do not share
memory. The expensive failure mode is not a bug; it is an agent quietly
reversing a decision that was argued through weeks earlier, because nothing in
the repository told it the decision existed.

Several of the choices here look wrong at first glance — using Postgres as a
work queue, running the model outside Docker, refusing to retry a blocked
request. Each has a reason. Without that reason written down, a reasonable
agent will "fix" them.

## Decision

Every structural decision gets a numbered ADR in `docs/adr/`. Records are
immutable: a changed decision means a new ADR that supersedes the old one.

Every ADR states its **cost**. A record that only lists benefits has not been
thought through and should be sent back.

`AGENTS.md` points here, and agents are instructed to read the relevant ADR
before changing anything structural.

## Consequences

- Decisions survive context loss between sessions.
- Disagreement is cheap: write a superseding ADR with the new reasoning.
- **Cost:** a real tax on every structural change, and a temptation to write
  ADRs for choices that do not need one. Keep them to decisions with genuine
  alternatives and genuine consequences. A library choice is usually not one.
