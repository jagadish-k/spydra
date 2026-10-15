<img src="design/logo/spydra-lockup-horizontal.svg" alt="Spydra" width="200" />

A single-user, locally-hosted crawler that discovers and extracts structured
product data from bespoke supplier and e-commerce sites, using a local LLM to
**propose** extraction rules that you approve before any domain goes live.

The model proposes once per template. It never runs during a crawl.

---

## Status

**Design complete, implementation not started.** This repository holds the
architecture, the design system, static mockups of all ten screens, and a
full development handoff: specs, ADRs and a phased build plan. No application
code yet.

**Starting development?** Read [`AGENTS.md`](AGENTS.md), then
[`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md). Phase 0 is scaffolding.

---

## Repository layout

```
AGENTS.md            Operating rules for anyone — human or agent — working
                     here. Read first, every session.

docs/
  README.md          Documentation index and reading order
  BUILD_PLAN.md      Seven phases, tasks, exit criteria. What to do next.
  ARCHITECTURE.md    System design. The source of truth for intent.
  DATA_MODEL.md      Core Postgres schema (specs/001 closes its gaps)
  DEVELOPMENT.md     Docker-native environment, commands, macOS gotchas
  TESTING.md         Test strategy: what must be covered and why
  DESIGN_SYSTEM.md   Tokens, typography, components, anti-patterns
  SCREENS.md         What each screen is for and what it contains
  BRAND.md           Logo construction, variants, usage rules
  WORKFLOW.md        Branches, the two gates, and the agent team
  agents/            Agent roles — canonical, tool-neutral. Edit these
  PHASE0_PROMPT.md   The prompt that starts a build session
  deck/              Developer briefing deck (open index.html from disk)
  adr/               Twenty-two decision records, each with its stated cost
  specs/             Fourteen component specs with acceptance criteria

design/
  tokens/            tokens.css (runtime) · tokens.json (W3C, for Figma)
  logo/              Six SVG variants + the generator that produces them
  mockups/           Static reference implementation of all ten screens

scripts/
  gen-agents.py      docs/agents/ → the four tool formats. Stdlib only

.claude/ .cursor/ .opencode/ .agents/
                     GENERATED agent definitions, one set per tool.
                     Edit docs/agents/ and run `make agents`.
.claude/hooks/       Optional Claude Code guards. The real gate is .githooks/
.githooks/           pre-commit · commit-msg · pre-push. `make hooks` wires them
.tasks/              One handoff file per branch (ADR-0022)

docker/              Dockerfiles, Caddyfile, init-schemas.sql
compose.yaml         Seven services
```

Design tokens are `--sp-*` prefixed and mapped to Tailwind v4 by
`design/tokens/tailwind-theme.css`, which also removes the default palette so
raw colour classes fail to compile.

## Shape

Seven services, each owning its own data:

```
browser → edge (Caddy, :8080)
            ├── /                          → web     React 19 SPA
            ├── /api/ui/*                  → bff     Fastify · ui schema
            └── /api/crawler/*             → api     FastAPI · crawl schema
                                                      │
                          worker (crawls, scales) ────┤
                          render  (Playwright sidecar)┘
                          db      PostgreSQL 18
```

Plus `llama-server` on the host — it proposes selectors during onboarding and
is never in the crawl path.

**Stack:** Python 3.15 · FastAPI · SQLAlchemy Core + Alembic · PostgreSQL 18
— Node 26 · Fastify 5 — React 19 · TypeScript · Vite · Tailwind v4 —
Playwright in a sidecar, all of it in Docker.

Rationale for every choice in [`docs/adr/`](docs/adr/README.md); start with
[ADR-0015](docs/adr/0015-service-topology.md).

## Viewing the mockups

```sh
open design/mockups/index.html
```

No build step and no server — they are plain HTML and open straight from disk.
The theme toggle in the top bar persists per browser; **light is the default**
unless your OS asks for dark on a first visit.

Start at `foundations.html` for the design system, or `template-review.html` for
the screen that matters most.

## Regenerating the logo

```sh
python3 design/logo/build_logo.py
```

All six variants derive from one 64×64 lattice. Edit the geometry constants at
the top of that file and every variant follows — which is what keeps the favicon
a true subset of the mark rather than a lookalike that drifts.

---

## The shape of the system, in short

**Postgres is the queue.** Not Kafka. Politeness is per-domain state (next
eligible time, backoff, token bucket) and a broker gives you ordered partitions,
not per-key rate limiting — so you would maintain the scheduler externally
anyway. More importantly, a Postgres queue makes dequeue and result-write
atomic; a broker splits them across two systems and hands you a dual-write
problem for no benefit.

**Three worker pools, one politeness gate.**

| Pool | Concurrency | Per-host limit |
| --- | --- | --- |
| Static pages | 8–16 | 1, with a 2 s gap |
| Rendered pages | 3 contexts | 1, same gate |
| Assets | 16–32 | 4–6, with a 200 ms gap |

Assets parallelise within a host because an image is a static byte range,
usually cached, costing the origin almost nothing — six concurrent image fetches
is what a real browser does to render one page. A product page is a dynamic
request that costs the origin CPU and reads as a crawl pattern in their logs, so
it stays sequential. Pages are gated in Postgres because the limit must hold
across worker replicas; asset concurrency is an in-process semaphore because a
loose limit is not a correctness concern.

**Extraction is a chain, cheapest rung first:** structured data (JSON-LD,
microdata) → approved category selectors → LLM-proposed selectors → the unknown
queue. Every proposal is **verified deterministically** against the real DOM
before you ever see it, which turns a probabilistic suggestion into a checked
candidate.

**Templates are versioned, never edited in place,** and keyed on
`(domain, url_pattern)` rather than domain alone. Every observation records the
template version that produced it — without that, a price change caused by your
own selector edit is indistinguishable from a real one, and the distinction
cannot be retrofitted.

**Observations are append-only.** Current state is a view. Only raw HTML is
purged, on a 7-day TTL.

**Getting blocked stops the crawler rather than triggering a retry.** A retry
loop against a site that has decided to block you is how a temporary block
becomes a permanent one.

## Deployment

Three containers — `db`, `api`, `worker` — plus **`llama-server` running natively
on the host**. Docker Desktop on macOS has no Metal GPU passthrough, so a
containerised model would run on CPU inside the VM and lose most of the Ultra's
advantage. Containers reach it at `host.docker.internal:8080`.

`/data` is a bind mount, not a named volume: you want images and HTML visible in
Finder, backed up by Time Machine, and surviving `docker compose down -v`.

## Known open questions

- **JS rendering prevalence.** Both fetch adapters ship in phase 1, so this no
  longer gates the design — but it sizes the run. The rendered pool caps at 3
  contexts against 8–16 static workers, so if most domains need rendering, page
  throughput drops roughly 4×.
- **Supplier data shape.** "Vendor information, supplier details" may be
  structured tables on some sites and free prose on others. JSONB absorbs either,
  but querying consistently across suppliers needs a normalisation pass.
- **Review throughput, not technology, is the constraint.** At one template per
  domain and six domains a month, 1,200 domains is roughly sixteen years away.
  Batch review is built in from phase 3 for this reason; tiered coverage stays
  unbuilt until the coverage report shows the backlog growing faster than you
  clear it.
- **Legal posture.** Crawling bespoke supplier catalogues raises terms-of-service
  questions separate from the technical ones. Worth checking the ToS of the first
  few targets — a real input to which domains get onboarded.
