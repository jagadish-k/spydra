# Component specifications

**Read [010](010-service-topology.md) first** — it describes the six-service
shape the rest of these sit inside.

One spec per component. Each states the contract, the shape of the data, the
edge cases that matter, and what "working" means. Read the relevant spec
before implementing; read `docs/adr/` before changing one.

| Spec | Component | Phase |
| --- | --- | --- |
| [001](001-domain-model.md) | Domain model and database schema | 1 |
| [002](002-scheduler.md) | Scheduler, politeness and the three pools | 1 |
| [003](003-extraction.md) | Extraction chain and validation | 1 |
| [004](004-discovery.md) | Discovery, canonicalisation and traps | 2 |
| [005](005-api.md) | HTTP API and SSE | 3 |
| [006](006-frontend.md) | React application | 3 |
| [007](007-llm-proposals.md) | LLM proposal and verification | 4 |
| [008](008-assets.md) | Asset pipeline | 5 |
| [009](009-observability.md) | Logging, metrics and operational surfaces | ongoing |
| [010](010-service-topology.md) | Service topology, routing and data ownership | 0 |
| [011](011-bff.md) | BFF: scheduling, saved views, aggregation | 3 |
| [012](012-render-sidecar.md) | Render sidecar | 1 |

Where a spec and `docs/ARCHITECTURE.md` disagree, the spec is more specific
and wins on detail; the architecture doc wins on intent. If they disagree on
intent, that is a bug in the docs — raise it.
