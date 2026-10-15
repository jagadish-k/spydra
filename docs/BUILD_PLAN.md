# Build plan

Seven phases. **Each ends with something that runs end to end** — not a layer,
not a set of classes, but a thing you can execute and watch work.

The order follows **risk, not interest**. Phases 0–2 contain everything that
is hard to change later: queue semantics, the politeness model, URL
canonicalisation, the observation schema. Phases 4–6 are additive and slot
into ports that already exist.

> The common failure mode for a project like this is to build the model
> integration first because it is the novel part, then discover the scheduler
> cannot support it. The strategy chain and the `LLMClient` port are designed
> so phase 4 adds a rung and an adapter, nothing more. **Do not reorder.**

## How to use this

- Work one phase at a time, top to bottom. Tasks within a phase may be
  reordered where there is no dependency.
- Tick boxes as you go. The box is ticked when the **definition of done** in
  `AGENTS.md` holds — not when the code is written.
- A phase is complete when its **exit criteria** pass. Demonstrate them; do
  not assert them.
- If a task turns out to need a decision that is not in `docs/adr/`, stop and
  write the ADR first.

---

## Phase 0 — Scaffold

*Nothing works yet. The goal is that `make check` passes on an empty project,
so every later phase has a gate to pass.*

- [ ] `0.1` Repository skeleton per `AGENTS.md` § Repository layout —
      `backend/`, `bff/`, `render/`, `frontend/`, `docker/`.
- [ ] `0.2` Dockerfiles: `api`, `worker` (**no browser**), `render`
      (Playwright Node image), `bff`, `web`.
- [ ] `0.3` `compose.yaml` per `DEVELOPMENT.md` — seven services, the
      `egress` network for `render`, `shm_size: 1gb`, named volumes for both
      `node_modules` and the venv, `extra_hosts` for the host LLM.
- [ ] `0.4` `docker/Caddyfile` with the four routes. **Verify SSE is not
      buffered** before moving on — the rule ordering and `flush_interval -1`
      are the two ways to get this wrong (spec 010 §2).
- [ ] `0.5` `docker/init-schemas.sql` — `crawl` and `ui` schemas, two roles,
      grants. Assert the BFF role cannot write `crawl` (spec 010 §3).
- [ ] `0.6` `Makefile` with every target in `DEVELOPMENT.md § Commands`,
      including the granular ones the hooks call: `fmt-staged`,
      `fmt-staged-js`, `typecheck-changed`, `typecheck-changed-py`,
      `agents`, `generated`, `hooks`. **`make agents` runs
      `scripts/gen-agents.py` on the host's `python3`, not in a container** —
      it has no dependencies and must work from any tool's terminal before
      the images exist.
- [ ] `0.6b` `make hooks` wires `core.hooksPath` to `.githooks/`. Verify all
      three hooks fire: a long commit subject is rejected, a staged `.env` is
      rejected, and a push to `develop` is refused (`docs/WORKFLOW.md` §2).
- [ ] `0.6c` Drizzle wiring (ADR-0021): `bff/drizzle.config.ts` with
      `schemaFilter: ['ui']`, `make revision-ui`, `make drizzle-pull`, and the
      test asserting every file in `bff/drizzle/` mentions only `ui.`.
- [ ] `0.7` Backend: FastAPI with `GET /api/crawler/healthz`, ruff + mypy
      strict + import-linter. The contract forbids `domain/` importing
      `adapters/`.
- [ ] `0.8` BFF: Fastify with `GET /api/ui/healthz`, TypeBox, ESLint,
      OpenAPI document published, **Drizzle connected to `ui`** with one
      trivial table proving generate → migrate → migrate-down works.
- [ ] `0.9` Render sidecar: `POST /render` + `GET /healthz`, context pool,
      resource blocking (spec 012).
- [ ] `0.10` Frontend: Vite + React 19 + TS strict; `styles/theme.css`
      importing `tokens.css` and `tailwind-theme.css`; ESLint flat + Prettier.
      **Assert `bg-red-500` fails the build** (ADR-0018).
- [ ] `0.11` Alembic initialised (`crawl`) + drizzle-kit initialised (`ui`);
      empty baselines run both ways under `make migrate` / `make migrate-down`.
- [ ] `0.11b` `make generated` produces `schema.crawler.d.ts`,
      `schema.ui.d.ts`, `bff/src/db/schema/crawl.generated.ts` and the four
      sets of agent adapters, and `make check` fails when any of them is
      stale. **Prove it by changing a `crawl` column and watching the BFF
      build break**, and by editing a role in `docs/agents/` without
      regenerating.
- [ ] `0.12` pytest + vitest + the BFF suite wired, one trivial test each.
- [ ] `0.13` CI running `make check` on a clean checkout, plus
      `make migrate-down`.
- [ ] `0.14` Agent team smoke test: run one trivial slice
      (`chore/0.14-hello-slice`) end to end — planner writes
      `.tasks/<branch>.md`, an implementer changes one file, `spydra-test`
      adds one test, `spydra-reviewer` reads the diff, `spydra-integrator`
      runs `make check` and opens the PR. **The point is to find out whether
      the handoff works while the stakes are a hello-world**, not to produce
      the change.

**Exit:** `make up` gives a working stack reachable at
`http://localhost:8080`; `make check` is green; the frontend renders a page
using a design token and the theme toggle works; an SSE test endpoint
streams through the edge **unbuffered**; the BFF cannot write `crawl`; the
three git hooks fire; and one slice has been through the full agent handoff.

> `0.4` and `0.5` are the two that will cost you a day each if deferred.
> Buffered SSE looks like a frontend bug, and a missing grant looks like
> nothing at all until the BFF quietly writes a table it should not.

> **Run phase 0 as one branch** (`chore/phase-0-scaffold`), mostly
> sequentially. There is nothing to parallelise yet and the hooks do not
> fully exist until `0.6`. The agent team starts paying for itself at phase 1
> (`docs/WORKFLOW.md` §5).

---

## Phase 1 — Crawl one domain, both fetch paths

*No UI, no model. The scheduler and the data model are the two things most
expensive to get wrong, so they come first and are proven in isolation.*

- [ ] `1.1` Full schema migration — `DATA_MODEL.md` **plus the gaps closed in
      spec 001 §1** (`runs`, `run_events`, `asset_queue`, `template_samples`,
      `parent_template_id`) **and the four schema corrections in spec 001
      §1** (`archived` state, `render_mode` values, `in_flight`,
      `asset_concurrency`).
- [ ] `1.2` Domain entities and the lifecycle transition function (spec 001
      §2–3). Pure, no I/O.
- [ ] `1.3` `Frontier` port + `PostgresFrontier`: the claim query, lease
      expiry sweep, completion (spec 002 §1–3).
- [ ] `1.4` Politeness gate: jitter, backoff, 403 handling, robots.txt with
      `Crawl-delay` as a floor (spec 002 §4–5).
- [ ] `1.5` `Fetcher` port + `HttpxFetcher`.
- [ ] `1.6` `RenderServiceFetcher` behind the same port — HTTP to the
      sidecar, with the 503-as-backpressure handling (spec 002 §6, spec 012).
- [ ] `1.7` Extraction chain with the `structured` and `selector` rungs,
      transforms and validation (spec 003).
- [ ] `1.8` Observation writes with `content_hash` over normalised fields.
- [ ] `1.9` Worker process running the static and rendered pools.
- [ ] `1.10` A YAML template loader so a domain can be configured without a UI.

**Exit:** one static domain **and** one JS-rendered domain crawled politely
end to end, data in Postgres, from a YAML template. Both fetchers exercised
by the same scheduler. The politeness tests in `TESTING.md §2` pass. Stopping
the `render` service leaves static crawling unaffected.

> Both adapters ship here deliberately. A port with one implementation is an
> untested abstraction, and rendering is a supported capability rather than a
> contingency.

---

## Phase 2 — Discovery and the queue

*Turn a seed into a full product set without wandering off-site or exploding
on facets.*

- [ ] `2.1` URL canonicalisation and `url_hash` (spec 004 §2).
- [ ] `2.2` Link extraction from discovery rules; allow/deny patterns; depth.
- [ ] `2.3` Dedupe within a run; enqueue with breadth-first ordering.
- [ ] `2.4` Trap defences: per-run URL cap, depth cap, repeating-path
      detection, scheme and length rejects (spec 004 §3).
- [ ] `2.4b` Mega-menu containment: a `subcategory_links` rule is scoped to
      its container, and the dry-run reports when a rule discovers the whole
      tree at depth 0 (spec 004 §3a). This is the discovery bug that looks
      like a working rule.
- [ ] `2.5` Run lifecycle — create, pause, stop, complete; `runs.stats`.
- [ ] `2.6` `run_events` writer (needed by phase 3's SSE, built here because
      the worker emits them).
- [ ] `2.7` CSV seed parsing with per-row validation (no HTTP yet).
- [ ] `2.8` Dry-run discovery as a library function (spec 004 §4).

**Exit:** a category seed yields the full product set for a real domain
without leaving it and without a facet explosion; the dry-run reports what
would be enqueued, grouped by matching rule.

---

## Phase 3 — API, UI and review

*The operator can onboard a domain without touching the filesystem.
Selectors are still hand-written; the model comes next.*

- [ ] `3.1` Crawler API: domains, seeds, templates, runs, pages (spec 005 §2).
- [ ] `3.1b` BFF: schedules with the fire loop, saved views, preferences, and
      `GET /api/ui/overview` (spec 011). The scheduling loop's once-only
      firing is the part to test properly.
- [ ] `3.2` SSE endpoint with `Last-Event-ID` backfill from `run_events`
      (spec 005 §3). **Backfill is part of this task, not a follow-up.**
- [ ] `3.3` `make types` wired for **both** schemas; generated client
      (ADR-0013, ADR-0015).
- [ ] `3.4` Frontend shell: `AppShell`, routing, theme with no-flash load.
- [ ] `3.5` Design-system components (spec 006 §2) — build the whole set
      before the screens, so screens compose rather than improvise.
- [ ] `3.6` Domains screen, sorted by health ascending, fed by the BFF's
      `/overview` in **one** request.
- [ ] `3.6b` Schedules screen — list, create, edit, fire history.
- [ ] `3.7` Domain detail with template versions and diff.
- [ ] `3.8` Seeds screen with the mandatory preview step.
- [ ] `3.9` **Template review screen** — three panes, live re-resolve,
      sample matrix, discovery rules with dry-run.
- [ ] `3.10` **Batch review** — the same review state rendered as a grid.
      Ships now, not later (ADR-0005, `SCREENS.md` §4).
- [ ] `3.11` Run monitor, SSE-driven, with the two throughput series.
- [ ] `3.12` Runs history with run comparison.
- [ ] `3.13` Products browser with observation history and field diff.
- [ ] `3.14` Playwright e2e: seed → template → approve → run → inspect.

**Exit:** a domain goes from seed URL to crawled product data entirely
through the UI, and a schedule fires a run unattended. Closing the laptop
mid-run and reopening shows no gap. Stopping the BFF does not affect a
running crawl.

> **Re-read [ADR-0015](adr/0015-service-topology.md) at the end of this
> phase.** If the BFF turned out to be mostly pass-through, collapse it and
> move scheduling into Python. Answer that honestly rather than keeping a
> tier because it is already there.

> `3.5` before `3.6`–`3.13` is the point. Screens built before their
> components produce nine one-off layouts that drift.

---

## Phase 4 — LLM proposals and chat authoring

*The model enters. By now the scheduler, the chain and the review screen all
exist, so this adds a rung and an adapter.*

**4a — the model (spec 007)**

- [ ] `4.1` `LLMClient` port + `LlamaServerClient`, with the fake used by
      tests.
- [ ] `4.2` DOM skeletonisation (spec 007 §2), with the node budget and
      stable node indices.
- [ ] `4.3` Proposal request with JSON-schema-constrained output.
- [ ] `4.4` **Deterministic verification** (spec 007 §4). Non-negotiable.
- [ ] `4.5` **Best-of-N: N=5 at temp 0.7, the ADR-0020 scorer, per-field
      merging.** Do not build the single-greedy-sample version first; the
      scorer is what makes the proposals usable.
- [ ] `4.6` Derived confidence, including the `nth-of-type` cap; escalation
      to the dense model for fields scoring below 60.
- [ ] `4.7` `POST /templates/{id}/propose`; `awaiting_approval` transition.
- [ ] `4.8` Unknown-pages inbox, grouped by `(domain, reason, url_pattern)`.
- [ ] `4.9` Dismiss-as-not-a-product-page adds a deny pattern.
- [ ] `4.10` DOM-skeleton toggle in the review preview.
- [ ] `4.11` Degradation: `llama-server` down blocks onboarding only.

**4b — the draft (spec 013)**

- [ ] `4.12` `crawl.template_drafts` and `crawl.field_vocabulary` migrations;
      vocabulary seed + the test asserting `column_name` names a real column.
- [ ] `4.13` `TemplateDraft` + `FieldCandidate` domain objects, provenance
      and verification sub-objects included from the start.
- [ ] `4.14` The shared verify → merge-per-field → rank pipeline. **One
      implementation, used by all three modes.** If a second appears, ADR-0019
      has been broken.
- [ ] `4.15` Draft API surface (spec 013 §5); `approve` promotes to a new
      template version and discards the draft.
- [ ] `4.16` Retrofit form-mode review (phase 3) onto drafts, so the
      hand-written path and the model path share one state shape.
- [ ] `4.17` Chat endpoint over SSE, with the hard limits enforced
      server-side — five sample pages, one domain, cannot start a run,
      cannot write `templates`.
- [ ] `4.18` Authoring chat screen (SCREENS §10) with provenance badges and
      the visible sample-page counter.
- [ ] `4.19` Draft purge sweep for `discarded` rows older than 30 days.

**Exit:** a new domain goes from seed URL to approved template without a
selector being written by hand, by chat or by `propose`. The chat refuses a
sixth sample page and says why. With `llama-server` stopped, crawling is
unaffected.

---

## Phase 5 — Assets, reports and hardening

*Everything that is additive and benefits from real data to tune against.*

- [ ] `5.1` Asset queue, pool and `AssetGate` (spec 008).
- [ ] `5.2` Hash-before-decode, resize, WebP, sharded content-addressed paths.
- [ ] `5.3` Asset safety limits — size, type sniffing, decompression bombs.
- [ ] `5.4` Backpressure from asset queue depth onto page workers.
- [ ] `5.5` Broken-template detector — the 20% threshold halting a domain.
- [ ] `5.6` Reports: extraction health, broken templates, price changes,
      new/missing, politeness, coverage. CSV + JSON export.
- [ ] `5.7` Reports screen.
- [ ] `5.8` HTML purge sweep on the 7-day TTL; pre-run disk check.
- [ ] `5.9` Render-path hardening — sidecar replica count, recycle
      thresholds, per-domain `render_mode` overrides, `auto` fallback
      recording `strategy = static_fallback`.
- [ ] `5.10` Observability pass against spec 009.

**Exit:** a full run over several domains produces images, reports and a
coverage number. The crawl-politeness report is defensible evidence.

---

## Phase 6 — Visual playground

*Last because it is the most build for the least risk, and because it needs
the draft pipeline and the sidecar to already be solid. It is also the phase
most likely to change shape once phases 4–5 have shown where the review time
actually goes — so do not start it early.*

- [ ] `6.1` `POST /inspect` on the sidecar (spec 014 §2) — full-page
      screenshot, element geometry, skeleton, **sharing the existing context
      cap and the egress-only network**.
- [ ] `6.2` Full-page scroll before capture, so lazy-loaded content has
      boxes.
- [ ] `6.3` Attribute and class filtering (spec 014 §3) — hashed, utility and
      state classes rejected before generalisation.
- [ ] `6.4` Inspect cache, 30 min, keyed `(url, viewport, full_page)`. **Cache
      hits claim no politeness lock; misses do.**
- [ ] `6.5` Layer 1 generalisation — heuristic ancestor walk, top three
      candidates emitted, not one.
- [ ] `6.6` Layer 2 generalisation — multi-example index elimination. This is
      the layer that earns the phase; budget accordingly.
- [ ] `6.7` Layer 3 — LLM refinement, only below score 60, selectors only.
- [ ] `6.8` Repeating-container detection with all three confirmations
      (siblings, structural similarity, geometry).
- [ ] `6.9` `POST /drafts/{id}/select`; examples persisted in provenance.
- [ ] `6.10` Select and Skeleton modes on the review screen's left pane,
      ancestor walk on `[` / `]`, all matches highlighted.
- [ ] `6.11` `reveal` steps (spec 014 §2a) with every bound enforced, plus
      `network[]` capture. The bounds are the feature; an unbounded version
      is a different program.
- [ ] `6.11b` Promote a network-log endpoint to a discovery rule
      (spec 004 §3a, case C), and a `json_source` discovery rule for menus
      whose data ships as inline JSON.
- [ ] `6.12` Re-generalisation from stored examples, for a template broken by
      a redesign. This is the payoff for storing provenance.

**Exit:** a listing and a product template are authored for a previously
unseen domain entirely by clicking, container included, and the result is
indistinguishable in shape from a hand-written template. A selector built
from clicks on two sample pages survives a positional change on a third.

---

## Deferred

Not in the plan; revisit only with a reason.

| Item | Why deferred |
| --- | --- |
| Full-text search over descriptions | Postgres `tsvector` when there is a query to serve |
| Export pipeline | Build the exporter when the target format is known |
| Template inheritance resolution | Column exists, logic does not (ADR-0006) |
| Tiered coverage / best-effort mode | Until the coverage report shows the backlog growing faster than it clears |
| Proxy rotation | If it is needed, the polite-crawling assumptions have already failed |
| Free-threaded Python (`cp315t`) | Dependencies ship it; nothing needs it yet (ADR-0017) |
| Replacing the render sidecar with browserless | The HTTP contract makes it a swap, not a rewrite |
| Scripted interaction recorder in the playground | Large build, large failure surface; bounded `reveal` and Skeleton mode cover nearly all of it (spec 014 §7) |

---

## Known risks

| Risk | Signal | Response |
| --- | --- | --- |
| **Review throughput, not technology, is the constraint.** At one template per domain and ~6 domains/month, 1,200 domains is ~16 years. | Coverage report backlog trend | Batch review ships in phase 3 for this reason. If the backlog still grows, tiered coverage becomes real work. |
| JS rendering more common than expected | Share of domains needing `rendered` after phase 1 | Rendered pool caps at 3 contexts against 12 static workers, so page throughput drops ~4×. Sizing problem, not a design problem. |
| Supplier data shape varies wildly | `attributes`/`supplier` JSONB diverging across domains | JSONB absorbs it; a normalisation pass is unscoped work if cross-supplier querying is needed. |
| Postgres queue contention | `crawl_queue` index bloat, slow claims | Not expected at this scale. The `Frontier` port is the escape hatch (ADR-0002). |
| **The BFF turns out to be a thin proxy** | After phase 3, count its routes that do real work vs forward | Collapse it; move scheduling into Python (ADR-0015) |
| Bleeding-edge stack has thin community knowledge | Time lost to first-encounter problems on Python 3.15 / Tailwind v4 | Budget for it. The docker-native constraint makes a revert one tag away (ADR-0017). |
| Legal posture | — | Check the ToS of the first targets. A real input to which domains get onboarded. |
