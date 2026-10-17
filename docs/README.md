# Spydra documentation

Start with [`../AGENTS.md`](../AGENTS.md) — the operating rules — then
[`BUILD_PLAN.md`](BUILD_PLAN.md) for what to do next.

## Orientation

| Doc                                    | Read it when                                                                                    |
| -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [`../AGENTS.md`](../AGENTS.md)         | Every session, first. Rules, stack, commands, definition of done.                               |
| [`BUILD_PLAN.md`](BUILD_PLAN.md)       | Every session. Which phase you are in and what "done" means.                                    |
| [`DEVELOPMENT.md`](DEVELOPMENT.md)     | Before running anything. Docker topology, commands, macOS gotchas.                              |
| [`TESTING.md`](TESTING.md)             | Before writing tests. What must be covered and why.                                             |
| [`WORKFLOW.md`](WORKFLOW.md)           | Before your first commit. Branches, the two gates, and which agent owns which part of a change. |
| [`agents/`](agents/README.md)          | Changing how an agent role behaves. Canonical, tool-neutral; `make agents` generates the rest.  |
| [`PHASE0_PROMPT.md`](PHASE0_PROMPT.md) | Starting a build session. The prompt to paste, and why it is shaped that way.                   |

## Design

| Doc                                  | Content                                                                     |
| ------------------------------------ | --------------------------------------------------------------------------- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Why the system is shaped this way. Intent; the specs hold the exact shapes. |

| [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Tokens, typography, components, anti-patterns. |
| [`SCREENS.md`](SCREENS.md) | What each of the ten screens is for. |
| [`UI_STATES.md`](UI_STATES.md) | The state matrix — which states every component and screen has. Binding on phase 3 (ADR-0025). |
| [`BRAND.md`](BRAND.md) | Logo construction, variants, usage. |
| [`deck/index.html`](deck/index.html) | **Developer briefing deck.** Sixteen slides: the problem, the five decisions worth arguing about, the screens, and where to start. Open it from disk; arrow keys, `o` for an overview, `p` for presenter notes, Cmd-P prints to PDF. |

The UI specification is two files (ADR-0025): `design/mockups/` for layout,
spacing, typography and colour — static HTML, opens from disk, accurate —
and `UI_STATES.md` for which states exist. The mockups are populated-state
only; build to match both.

## Decisions

[`adr/`](adr/README.md) — twenty-four records. Read the relevant one before
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
