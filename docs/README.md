# Spydra documentation

Start with [`../AGENTS.md`](../AGENTS.md) — the operating rules — then
[`BUILD_PLAN.md`](BUILD_PLAN.md) for what to do next.

## Orientation

| Doc | Read it when |
| --- | --- |
| [`../AGENTS.md`](../AGENTS.md) | Every session, first. Rules, stack, commands, definition of done. |
| [`BUILD_PLAN.md`](BUILD_PLAN.md) | Every session. Which phase you are in and what "done" means. |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Before running anything. Docker topology, commands, macOS gotchas. |
| [`TESTING.md`](TESTING.md) | Before writing tests. What must be covered and why. |

## Design

| Doc | Content |
| --- | --- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design. The source of truth for intent. |
| [`DATA_MODEL.md`](DATA_MODEL.md) | Core schema. **Incomplete** — [spec 001](specs/001-domain-model.md) closes the gaps. |
| [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Tokens, typography, components, anti-patterns. |
| [`SCREENS.md`](SCREENS.md) | What each of the ten screens is for. |
| [`BRAND.md`](BRAND.md) | Logo construction, variants, usage. |

The UI specification is `design/mockups/` — static HTML, opens from disk,
accurate. Build to match it.

## Decisions

[`adr/`](adr/README.md) — fourteen records. Read the relevant one before
changing anything structural. Each states its cost.

The four most likely to be questioned, and most likely to be wrong to change:

- [ADR-0002](adr/0002-postgres-as-queue.md) — Postgres is the queue. Not Kafka, not Redis.
- [ADR-0004](adr/0004-stop-on-block.md) — a block stops the crawler. Never retry through it.
- [ADR-0005](adr/0005-llm-proposes-only.md) — the model proposes; it never extracts.
- [ADR-0009](adr/0009-llama-server-on-host.md) — the model runs outside Docker, on purpose.

## Specifications

[`specs/`](specs/README.md) — one per component, each with acceptance
criteria. Read before implementing.

## Reading order for a new agent

1. [`../AGENTS.md`](../AGENTS.md)
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — long, but it is the intent
3. [`BUILD_PLAN.md`](BUILD_PLAN.md) — find the current phase
4. The spec for the component you are about to build
5. Any ADR that spec references
6. [`DEVELOPMENT.md`](DEVELOPMENT.md) — then `make up`
