# Architecture decision records

One file per decision, numbered, immutable once accepted. If a decision
changes, write a new ADR that supersedes the old one and mark the old one
superseded — do not edit history.

Numbers are never reused. 0011 is absent because it was withdrawn during
design, before anything was built against it.

Each record states the cost of the decision, not just its benefit. A decision
with no stated cost has not been thought through.

**Start with [0015](0015-service-topology.md)** — it describes the six-service
shape everything else sits inside.

| #                                         | Decision                                                                    | Status                                     |
| ----------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------ |
| [0001](0001-use-adrs.md)                  | Record architecture decisions                                               | Accepted                                   |
| [0002](0002-postgres-as-queue.md)         | Postgres is the queue and the datastore                                     | Accepted                                   |
| [0003](0003-three-pools-one-gate.md)      | Three worker pools behind one per-domain gate                               | Accepted _(rendered pool amended by 0016)_ |
| [0004](0004-stop-on-block.md)             | A block stops the crawler; it is never retried through                      | Accepted                                   |
| [0005](0005-llm-proposes-only.md)         | The LLM proposes selectors and never extracts                               | Accepted                                   |
| [0006](0006-versioned-templates.md)       | Templates are versioned and keyed on (domain, url_pattern)                  | Accepted                                   |
| [0007](0007-append-only-observations.md)  | Observations are append-only; current state is a view                       | Accepted                                   |
| [0008](0008-ports-and-adapters.md)        | Ports and adapters at four boundaries only                                  | Accepted                                   |
| [0009](0009-llama-server-on-host.md)      | llama-server runs natively on the host                                      | Accepted                                   |
| [0010](0010-docker-native-development.md) | All development runs in Docker                                              | Accepted                                   |
| [0012](0012-sse-for-progress.md)          | Server-Sent Events for live progress                                        | Accepted                                   |
| [0013](0013-generated-api-types.md)       | Frontend API types are generated from OpenAPI                               | Accepted                                   |
| [0014](0014-sqlalchemy-core-alembic.md)   | SQLAlchemy Core + Alembic, raw SQL where the query is the point             | Accepted                                   |
| [0015](0015-service-topology.md)          | Service topology: edge, BFF, API, worker, render sidecar                    | Accepted                                   |
| [0016](0016-render-sidecar.md)            | Headless rendering runs in a sidecar                                        | Accepted                                   |
| [0017](0017-version-policy.md)            | Track latest versions, behind a readiness gate                              | Accepted                                   |
| [0018](0018-react19-tailwind4.md)         | React 19 and Tailwind v4                                                    | Accepted                                   |
| [0019](0019-one-authoring-pipeline.md)    | One authoring pipeline, three input modes                                   | Accepted                                   |
| [0020](0020-best-of-n-verification.md)    | Best-of-N sampling, ranked by deterministic verification                    | Accepted                                   |
| [0021](0021-drizzle-for-bff.md)           | Drizzle for the BFF's database access                                       | Accepted                                   |
| [0022](0022-agent-team.md)                | Specialised agents, sequential within a slice                               | Accepted                                   |
| [0023](0023-render-egress-isolation.md)   | The render sidecar is reached through the host, not a shared network        | Accepted                                   |
| [0024](0024-drizzle-down-migrations.md)   | `ui` down-migrations: hand-written `down.sql`, run by a ledger-aware script | Accepted                                   |
