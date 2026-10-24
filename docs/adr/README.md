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

| #                                                                      | Decision                                                                    | Status                                     |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------ |
| [0001](0001-use-adrs.md)                                               | Record architecture decisions                                               | Accepted                                   |
| [0002](0002-postgres-as-queue.md)                                      | Postgres is the queue and the datastore                                     | Accepted                                   |
| [0003](0003-three-pools-one-gate.md)                                   | Three worker pools behind one per-domain gate                               | Accepted _(rendered pool amended by 0016)_ |
| [0004](0004-stop-on-block.md)                                          | A block stops the crawler; it is never retried through                      | Accepted                                   |
| [0005](0005-llm-proposes-only.md)                                      | The LLM proposes selectors and never extracts                               | Accepted                                   |
| [0006](0006-versioned-templates.md)                                    | Templates are versioned and keyed on (domain, url_pattern)                  | Accepted                                   |
| [0007](0007-append-only-observations.md)                               | Observations are append-only; current state is a view                       | Accepted                                   |
| [0008](0008-ports-and-adapters.md)                                     | Ports and adapters at four boundaries only                                  | Accepted                                   |
| [0009](0009-llama-server-on-host.md)                                   | llama-server runs natively on the host                                      | Accepted                                   |
| [0010](0010-docker-native-development.md)                              | All development runs in Docker                                              | Accepted                                   |
| [0012](0012-sse-for-progress.md)                                       | Server-Sent Events for live progress                                        | Accepted                                   |
| [0013](0013-generated-api-types.md)                                    | Frontend API types are generated from OpenAPI                               | Accepted                                   |
| [0014](0014-sqlalchemy-core-alembic.md)                                | SQLAlchemy Core + Alembic, raw SQL where the query is the point             | Accepted                                   |
| [0015](0015-service-topology.md)                                       | Service topology: edge, BFF, API, worker, render sidecar                    | Accepted                                   |
| [0016](0016-render-sidecar.md)                                         | Headless rendering runs in a sidecar                                        | Accepted                                   |
| [0017](0017-version-policy.md)                                         | Track latest versions, behind a readiness gate                              | Accepted                                   |
| [0018](0018-react19-tailwind4.md)                                      | React 19 and Tailwind v4                                                    | Accepted                                   |
| [0019](0019-one-authoring-pipeline.md)                                 | One authoring pipeline, three input modes                                   | Accepted                                   |
| [0020](0020-best-of-n-verification.md)                                 | Best-of-N sampling, ranked by deterministic verification                    | Accepted                                   |
| [0021](0021-drizzle-for-bff.md)                                        | Drizzle for the BFF's database access                                       | Accepted                                   |
| [0022](0022-agent-team.md)                                             | Specialised agents, sequential within a slice                               | Accepted                                   |
| [0023](0023-render-egress-isolation.md)                                | The render sidecar is reached through the host, not a shared network        | Superseded in part by 0038                 |
| [0024](0024-drizzle-down-migrations.md)                                | `ui` down-migrations: hand-written `down.sql`, run by a ledger-aware script | Accepted                                   |
| [0025](0025-ui-states-authority.md)                                    | `UI_STATES.md` is the state authority; the mockups are populated-state      | Accepted                                   |
| [0026](0026-claim-locks-the-domain-row.md)                             | The claim query locks the domain row, not just the queue row                | Accepted                                   |
| [0027](0027-no-required-fields.md)                                     | No field is ever required; emptiness is the only failure signal             | Accepted _(amended by 0037, 0039)_         |
| [0028](0028-httpx2-and-mocktransport.md)                               | httpx2 for the Fetcher; its own MockTransport instead of respx              | Accepted                                   |
| [0029](0029-deterministic-crawl-mirror.md)                             | The committed crawl mirror is normalised, not verbatim                      | Accepted                                   |
| [0030](0030-empty-needs-a-prior.md)                                    | An empty extraction only counts as a regression if the page once worked     | Accepted _(amended by 0037, 0039)_         |
| [0031](0031-figma-is-the-drawing-authority.md)                         | Figma is the drawing authority; `SCREENS.md` is the screen registry         | Accepted                                   |
| [0032](0032-everything-above-a-primitive-is-a-component.md)            | Everything above a primitive is a component; screens are compositions       | Accepted                                   |
| [0033](0033-current-state-skips-lightweight-rows.md)                   | Current state skips lightweight rows; "nothing comparable" has no hash      | Accepted                                   |
| [0034](0034-claim-only-a-domain-with-work.md)                          | The claim takes only a domain with work, for the pool that asks             | Accepted                                   |
| [0035](0035-ruamel-yaml-for-the-loader.md)                             | ruamel.yaml for the YAML template loader                                    | Accepted                                   |
| [0036](0036-fixture-site-on-egress-for-the-exit.md)                    | A test-only fixture service may join `egress`, behind a profile             | Accepted                                   |
| [0037](0037-empty-means-nothing-substantive.md)                        | An empty extraction is one with nothing substantive in it                   | Accepted                                   |
| [0038](0038-render-link-network.md)                                    | The worker reaches the sidecar over a two-member internal network           | Accepted                                   |
| [0039](0039-listing-pages-are-not-extraction-verdicts.md)              | A listing template's page is never an empty extraction verdict              | Accepted                                   |
| [0040](0040-cap-breach-is-a-run-scoped-halt.md)                        | A URL-cap breach is a run-scoped halt, not a domain state                   | Accepted                                   |
| [0041](0041-run-lifecycle-fenced-at-the-claim.md)                      | The run lifecycle is fenced at the claim                                    | Accepted                                   |
| [0042](0042-monotonic-per-run-event-sequence-from-a-counter-column.md) | Monotonic per-run event sequence from a counter column                      | Accepted                                   |
