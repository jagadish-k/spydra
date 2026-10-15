# Spydra — System Architecture Blueprint

> **Deployment and stack sections are superseded.** This document is still
> the source of truth for *intent* — the scheduler, politeness model,
> extraction chain, failure modes and phasing all stand. But the system is
> now six services rather than one Python app, and the versions have moved.
>
> | Superseded here | Current source |
> | --- | --- |
> | Single-app deployment, `docker compose` block | [specs/010-service-topology.md](specs/010-service-topology.md), [DEVELOPMENT.md](DEVELOPMENT.md) |
> | Playwright inside the worker | [ADR-0016](adr/0016-render-sidecar.md), [specs/012-render-sidecar.md](specs/012-render-sidecar.md) |
> | Python 3.12 / Postgres 17 / React 18 / Tailwind v3 | [ADR-0017](adr/0017-version-policy.md), [ADR-0018](adr/0018-react19-tailwind4.md) |
> | `tailwind.config.ts` | `design/tokens/tailwind-theme.css` |
> | Schema (incomplete, four errors) | [specs/001-domain-model.md](specs/001-domain-model.md) |

Exported from the design conversation · 14 Oct 2026

> Source of truth for system design. UI specifics live in `SCREENS.md`;
> visual language in `DESIGN_SYSTEM.md` and `BRAND.md`.

## Overview and scope

A single-user, locally-hosted crawler that discovers and extracts structured product data from bespoke e-commerce and supplier sites, using a local LLM to propose extraction rules that the operator approves before any domain goes live.

The system is deliberately a **single application with an embedded datastore**, not a distributed one. Every constraint below points away from the usual web-scale crawler architecture.

| Constraint | Value | Architectural consequence |
| --- | --- | --- |
| Users | One (the operator), local only | No auth, no multi-tenancy, no horizontal scaling |
| Domains | 2–3 onboarded at a time, growing toward \~1200 | Onboarding loop is the primary interface; crawling is the batch job |
| Worst failure | Being blocked by a remote site | Politeness is a correctness requirement, not a nicety |
| Seeds | Category/listing pages, entered via UI or CSV | Discovery layer required, with hard bounds |
| Crawl depth | 5, following pagination, subcategories, product links | Needs per-domain URL-pattern allowlists and a run-level URL cap |
| Cadence | Manual, infrequent | No scheduler; no need for a long-running daemon |
| Extraction | Operator-approved CSS/XPath per `(domain, url_pattern)` | Templates are versioned, first-class entities in Postgres |
| Model role | Propose selectors once per template; never per page | Inference speed is near-irrelevant; model quality matters |
| History | Append-only observations, change tracking | Observations table, not in-place updates |
| Host | Mac Studio Ultra, Docker + host-side llama-server | Unified memory allows a 30B-class model |

### Out of scope for v1

- Authentication, multi-user access, or remote deployment.
- Distributed crawling or any message broker.
- Scheduled/automated runs (the data model supports adding them later).
- JavaScript rendering is supported per-domain but is not the default path.

## Key decisions and rejected alternatives

The decisions that cost the most to reverse are the queue, the extraction strategy order, and the observation model. All three are settled below.

### Postgres as the frontier queue — not Kafka or SwiftMQ

Rejected. The reasoning, in order of weight:

1. **Dual-write risk.** With a broker, the crawled row lands in Postgres and the queue offset lands in the broker. A crash between them gives you duplicate crawls or silently dropped URLs. `SELECT ... FOR UPDATE SKIP LOCKED` makes dequeue-and-write a single transaction.
2. **Kafka's model fights the requirement.** Politeness is per-domain state — next-eligible time, backoff, failure count. Kafka offers ordered partitions and consumer offsets, not per-key rate limiting. The domain scheduler would live outside the broker regardless, so the broker contributes nothing to the hard part.
3. **Scale doesn't justify it.** Frontier queues exist for distributed crawls across many machines. 1200 domains on one Mac Studio is a rounding error; Postgres handles millions of queue rows comfortably.
4. **Operational cost.** A broker is another process to run, monitor, and recover — on a machine where you wanted a standalone app.

**Hedge:** the queue sits behind a `Frontier` port with a Postgres adapter. If a single node is ever outgrown, that interface is the swap point. This costs nothing now and preserves the option.

### Structured data before selectors

Extraction runs as a strategy chain, cheapest rung first: JSON-LD/microdata → approved selectors → LLM proposal → unknown queue. Even on bespoke supplier sites where `schema.org/Product` coverage is thin, the free rung costs one parse attempt and occasionally eliminates a template entirely.

### Short-TTL raw HTML retention

You initially wanted no HTML retained. Retention was added because **versioned selectors without stored content give you an audit trail you cannot act on** — "this selector was wrong" becomes "re-crawl the site," which is the stated worst failure mode. Gzipped HTML with a 7-day purge bounds the disk cost while covering the window in which extraction bugs actually surface.

### Append-only observations

Timestamps alone record *when* you looked, not *what changed*. Since change tracking is wanted, every crawl writes an observation row; current state is a view over the latest per page. Retrofitting history onto an in-place-update schema means reconstructing data that was never captured.

### llama-server on the host, outside Docker

Docker Desktop on macOS runs a Linux VM with no Metal passthrough. A containerised model falls back to CPU and discards most of the Ultra's advantage. The model runs natively; the app container reaches it at `host.docker.internal`.

### Deferred by default

- **robots.txt is respected**, with a per-domain override flag set consciously, logged when used.
- **No scheduler.** Runs are operator-triggered. The `runs` table and queue support cron-driven triggering later with no schema change.

## Component architecture

&#91;embedded content: component architecture · 3 containers, 1 host process\]

The API and the workers run the same codebase with different entry points. Workers never talk to the API — they coordinate entirely through Postgres, which is what makes replica count a free dial.

## Data model

Core fields are typed columns; variable per-site attributes (spec tables, supplier metadata) go in JSONB. Forcing both into one shape loses either validation or flexibility.

```sql
-- Domain registry: lifecycle, politeness config, rendering mode
CREATE TYPE domain_state AS ENUM
  ('discovered','awaiting_approval','active','paused','broken');

CREATE TABLE domains (
  id              BIGSERIAL PRIMARY KEY,
  host            TEXT NOT NULL UNIQUE,
  state           domain_state NOT NULL DEFAULT 'discovered',
  render_mode     TEXT NOT NULL DEFAULT 'static',   -- 'static' | 'browser'
  crawl_delay_ms  INT  NOT NULL DEFAULT 2000,
  max_concurrency INT  NOT NULL DEFAULT 1,
  respect_robots  BOOLEAN NOT NULL DEFAULT TRUE,
  user_agent      TEXT,
  next_eligible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consecutive_failures INT NOT NULL DEFAULT 0,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON domains (next_eligible_at) WHERE state = 'active';

-- Templates are scoped to (domain, url_pattern), NOT domain alone.
-- A domain commonly needs separate rules for listing vs product pages.
CREATE TABLE templates (
  id            BIGSERIAL PRIMARY KEY,
  domain_id     BIGINT NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  url_pattern   TEXT NOT NULL,        -- regex matched against path+query
  page_kind     TEXT NOT NULL,        -- 'listing' | 'product'
  version       INT  NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT FALSE,
  -- discovery rules (listing pages): how to find more URLs
  discovery     JSONB NOT NULL DEFAULT '{}',
  --   { next_page: "a.pagination__next",
  --     product_links: "a.product-card__link",
  --     subcategory_links: "nav.cats a",
  --     allow_patterns: ["^/catalog/"], deny_patterns: ["\\?sort="] }
  -- extraction rules (product pages): field -> selector + transform
  extraction    JSONB NOT NULL DEFAULT '{}',
  --   { price: { sel: ".price", attr: "text", transform: "currency",
  --              required: true },
  --     images: { sel: ".gallery img", attr: "src", many: true } }
  proposed_by   TEXT NOT NULL DEFAULT 'human',  -- 'human' | 'llm'
  approved_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (domain_id, url_pattern, version)
);
CREATE UNIQUE INDEX one_active_per_pattern
  ON templates (domain_id, url_pattern) WHERE is_active;

-- Page identity. One row per canonical URL, ever.
CREATE TABLE pages (
  id             BIGSERIAL PRIMARY KEY,
  domain_id      BIGINT NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  url            TEXT NOT NULL,          -- canonicalised
  url_hash       BYTEA NOT NULL,         -- sha256, for the unique index
  page_kind      TEXT,
  template_id    BIGINT REFERENCES templates(id),
  depth          INT NOT NULL DEFAULT 0,
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_crawled_at TIMESTAMPTZ,
  UNIQUE (domain_id, url_hash)
);

-- Append-only. One row per successful crawl. This is the history.
CREATE TABLE page_observations (
  id            BIGSERIAL PRIMARY KEY,
  page_id       BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  run_id        BIGINT NOT NULL REFERENCES runs(id),
  template_id   BIGINT REFERENCES templates(id),
  observed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  http_status   INT,
  content_hash  BYTEA,          -- skip the write when nothing changed
  strategy      TEXT,           -- 'structured' | 'selector' | 'llm'
  -- typed core fields
  title         TEXT,
  price_amount  NUMERIC(14,4),
  price_currency CHAR(3),
  availability  TEXT,
  vendor        TEXT,
  category_path TEXT[],
  description   TEXT,
  -- everything site-specific
  attributes    JSONB NOT NULL DEFAULT '{}',
  supplier      JSONB NOT NULL DEFAULT '{}',
  validation    JSONB NOT NULL DEFAULT '{}',  -- per-field pass/fail
  raw_html_path TEXT,           -- gzipped, purged after 7 days
  raw_html_expires_at TIMESTAMPTZ
);
CREATE INDEX ON page_observations (page_id, observed_at DESC);

-- Current state is a view, not a table.
CREATE VIEW page_current AS
SELECT DISTINCT ON (page_id) *
FROM page_observations ORDER BY page_id, observed_at DESC;

-- Work queue. SKIP LOCKED does the dequeue.
CREATE TABLE crawl_queue (
  id          BIGSERIAL PRIMARY KEY,
  run_id      BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  domain_id   BIGINT NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  url         TEXT NOT NULL,
  url_hash    BYTEA NOT NULL,
  depth       INT NOT NULL DEFAULT 0,
  state       TEXT NOT NULL DEFAULT 'pending',
  attempts    INT NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, url_hash)              -- dedupe within a run
);
CREATE INDEX ON crawl_queue (domain_id, state) WHERE state = 'pending';

-- Assets, deduped by content hash across all pages.
CREATE TABLE assets (
  id            BIGSERIAL PRIMARY KEY,
  content_hash  BYTEA NOT NULL UNIQUE,
  path          TEXT NOT NULL,
  mime          TEXT,
  width         INT,
  height        INT,
  bytes         BIGINT,
  downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE observation_assets (
  observation_id BIGINT REFERENCES page_observations(id) ON DELETE CASCADE,
  asset_id       BIGINT REFERENCES assets(id),
  source_url     TEXT NOT NULL,
  position       INT,
  PRIMARY KEY (observation_id, asset_id, source_url)
);

-- Pages the system could not interpret. Your review inbox.
CREATE TABLE unknown_pages (
  id           BIGSERIAL PRIMARY KEY,
  domain_id    BIGINT NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  url          TEXT NOT NULL,
  reason       TEXT NOT NULL,   -- 'no_template' | 'validation_failed' | ...
  llm_proposal JSONB,           -- selectors the model suggested
  sample_html_path TEXT,
  resolved_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Why these shapes

- **`templates` keyed on `(domain_id, url_pattern)`** — a domain needs different rules for listing and product pages, and often per category section. Keying on domain alone is a painful migration later.
- **Partial unique index on `is_active`** — guarantees exactly one live template per pattern while keeping every prior version readable.
- **`content_hash` on observations** — a re-crawl that finds nothing changed writes no row beyond a timestamp bump, keeping history meaningful rather than noisy.
- **`validation` JSONB per observation** — records which fields passed their rules at crawl time, so a silently broken selector surfaces in a report rather than as quiet bad data.

## The crawl pipeline

A run moves through three phases. All three share the same queue and the same politeness gate.

### 1. Seeding

Seeds enter from the UI (single URL) or CSV upload. The CSV template is fixed: `url, domain_hint, page_kind, notes`. Each seed is canonicalised, assigned to a domain row (created in `discovered` state if new), and enqueued at depth 0.

### 2. Discovery

From a listing page, the crawler extracts links using the **approved template's discovery rules** — not heuristics. This is the single most important safety property in the system: an unapproved domain discovers nothing, so it cannot wander.

Each extracted link is filtered through, in order:

1. **Same-host check.** Off-host links are dropped unless explicitly allowlisted.
2. **Pattern allowlist/denylist** from the template (`allow_patterns`, `deny_patterns`).
3. **Depth cap** of 5, inherited and incremented from the parent.
4. **Canonicalisation** — strip tracking parameters (`utm_*`, `gclid`, `fbclid`, session ids), normalise trailing slashes, lowercase the host, sort remaining query parameters. The canonical form is what gets hashed.
5. **De-duplication** against `crawl_queue (run_id, url_hash)` and against `pages`.
6. **Run-level URL cap** — a circuit breaker, default 10,000 per run per domain, configurable.

Faceted navigation is the classic trap: `?color=red&size=M&sort=price` generates a combinatorial URL space that looks like legitimate content. The `deny_patterns` list is where you kill it, and it is part of what you approve.

### 3. Fetch and extract

**Fetch** uses async `httpx` by default. A domain flagged `render_mode = 'browser'` is routed to a small Playwright worker pool instead (2–3 contexts, reused, not one per page). Mixed mode across domains in one run is supported.

**Extraction is a strategy chain.** Each rung is tried only if the previous one fails or is absent:

| Order | Strategy | Cost | When it applies |
| --- | --- | --- | --- |
| 1 | JSON-LD / microdata (`schema.org/Product`) | Free | Site emits structured data; most reliable where present |
| 2 | Approved template selectors | Free | An active template matches the URL pattern |
| 3 | LLM selector proposal | \~seconds, once per template | No template matches; result goes to review, not to data |
| 4 | Unknown queue | — | Nothing worked; page listed for your analysis |

Only rungs 1 and 2 produce stored observations. Rung 3 produces a *proposal*, which is why unapproved domains never generate data.

### Validation

Every extracted field is checked against its rule before the observation is written: `price` must parse as a currency amount, `title` must be non-empty, `images` must yield at least one resolvable URL. Required-field failures route the page to `unknown_pages` with reason `validation_failed`, and after a threshold (default 20% of a domain's pages in one run) the domain is marked `broken` and the run for that domain halts.

This is the defence against a site redesign silently turning a working template into one that returns empty strings. Without it, you get a clean-looking run full of nulls.

## Domain lifecycle and the approval loop

Domain state is explicit, stored on the domain row, and it gates everything. A domain that is not `active` consumes no crawl budget and sends no requests — which is why a stalled review queue costs you nothing operationally, and why "block until I approve" is a cheap guarantee rather than an expensive one.

| State | Meaning | Crawls? | Exit |
| --- | --- | --- | --- |
| `discovered` | Seeded, nothing known about it | No | A template proposal is requested |
| `awaiting_approval` | A proposal exists, verified, waiting on you | No | You approve or reject |
| `active` | At least one approved template | Yes | You pause, or it breaks |
| `broken` | Validation failures exceeded threshold | No | Re-review the template |
| `paused` | You paused it, or 3 consecutive 403s auto-paused it | No | You resume |
| `archived` | Retired, data retained | No | Terminal |

**The loop:** a seed enters → the domain is `discovered` → the crawler fetches one sample page per URL pattern (this is the only fetching an unapproved domain does, and it respects the same politeness gate) → the DOM is skeletonised and sent to the model → the proposal is verified deterministically against the real DOM → the domain moves to `awaiting_approval` → you review → approve promotes the template and moves the domain to `active`, which releases its seeds into the queue.

**Templates are versioned, never edited in place.** An approval creates a new row with an incremented version and flips `is_active`; the old version is retained. This is what makes a data change attributable: every observation records the template version that produced it, so a price that moved because the site changed is distinguishable from one that moved because you fixed a selector. Retrofitting that distinction later is impossible — the evidence is gone.

**A template is keyed on `(domain, url_pattern)`, not on domain alone.** You said template-per-domain *or* per-category-page, and a single site frequently needs different selectors for different sections. Keying on the domain alone works until the first site that doesn't, and the migration at that point touches every row.

**Breaking is a state transition, not an error log.** When validation failures exceed 20% of a domain's pages in a run, the domain moves to `broken` and stops crawling mid-run. The alternative — carrying on and recording thousands of empty extractions — is how a redesign quietly corrupts a dataset.

**On inheritance.** `templates.parent_template_id` exists as a nullable self-reference from day one and is never populated. If a platform family does turn up, a child template overriding a parent's field map is an additive change to the extraction chain, and the existing rows are already shaped for it. Until then it is a column nothing reads — which is the correct cost for a possibility you do not expect to materialise.

## Politeness and scheduling

Being blocked is your worst outcome, so the scheduler is the component to get right. It is a **per-domain gate in front of a shared worker pool** — not a global semaphore and not a per-domain thread.

### The shape

```python
# Conceptually: the scheduler answers one question cheaply.
#   "Which domain may I fetch from right now?"
# A min-heap on next_eligible_at, backed by the domains table.

async def claim_next(conn) -> QueueItem | None:
    return await conn.fetchrow("""
        WITH eligible AS (
            SELECT id FROM domains
            WHERE state = 'active' AND next_eligible_at <= now()
            ORDER BY next_eligible_at
            LIMIT 1
        )
        UPDATE crawl_queue q
        SET state = 'in_flight', locked_until = now() + interval '120 seconds',
            attempts = attempts + 1
        WHERE q.id = (
            SELECT q2.id FROM crawl_queue q2
            JOIN eligible e ON e.id = q2.domain_id
            WHERE q2.state = 'pending'
            ORDER BY q2.depth, q2.id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING q.*;
    """)
```

After each fetch the worker sets `domains.next_eligible_at = now() + crawl_delay_ms` (plus jitter). With 1200 domains at a 2 s delay and 50 workers, throughput is bounded by the pool, not by courtesy — the per-host constraint is nearly free once the domain count is high.

### Concurrency model

There are **two independent pools**, because HTML and assets have different risk profiles and different bottlenecks.

|  | Page pool | Asset pool |
| --- | --- | --- |
| Fetches | HTML (listing + product pages) | Images |
| Workers | 8–16 async tasks | 16–32 async tasks |
| Per-host limit | **1 concurrent**, 2 s gap | **4–6 concurrent**, 200 ms gap |
| Gated by | `domains.next_eligible_at` | `asset_hosts.semaphore` |
| Blocked response | pause the domain | pause assets only; pages continue |

Both pools run inside the same worker process, as two `asyncio.TaskGroup` loops over the same connection pool. They are separate queues, not separate services.

**Why assets may be parallelised within a host and pages may not.** A product page is a dynamic request: it hits application code, touches a database, costs the origin real CPU, and appears in their logs as a crawl pattern. An image is a static byte range, usually served from cache or a CDN edge, costing the origin almost nothing. Six concurrent image fetches is ordinary browser behaviour — a real browser opens exactly that many connections per host to render one page. One page request every two seconds plus bursty asset fetches is a traffic shape that looks like a visitor; sequential everything looks like a crawler.

The per-host asset cap still matters. Unbounded parallel fetching against one host is what trips rate limiters, and an image host that returns 429 must still back off — it is just that the backoff applies to the asset pool alone and does not stall page crawling.

**Pool sizing.** Page throughput is `min(workers, eligible_domains)`. With 2–3 domains active during onboarding you will see 2–3 concurrent page fetches no matter how many workers run — that ceiling is your politeness requirement, not a bug. The asset pool is where parallelism actually pays, since images are typically 70–80% of total bytes and a single product page can yield six of them.

**Decoupling.** Assets are enqueued, not fetched inline. A page worker extracts image URLs, inserts `asset_queue` rows, and moves on — it never blocks on image downloads. This matters because an image host can be slow or down without affecting the page crawl rate, and because it lets the asset pool keep working after page crawling for a domain has finished.

```python
# Two gates, two shapes.

# Pages: one at a time per domain, enforced in Postgres (see claim_next above).

# Assets: N at a time per host, enforced in-process.
class AssetGate:
    def __init__(self, per_host: int = 5, min_gap_ms: int = 200):
        self._sem: dict[str, asyncio.Semaphore] = {}
        self._next_ok: dict[str, float] = {}
        self._per_host, self._gap = per_host, min_gap_ms / 1000

    @asynccontextmanager
    async def acquire(self, host: str):
        sem = self._sem.setdefault(host, asyncio.Semaphore(self._per_host))
        async with sem:
            wait = self._next_ok.get(host, 0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_ok[host] = time.monotonic() + self._gap
            yield
```

An in-process semaphore is sufficient here precisely because the limit is loose. Page politeness lives in Postgres because it must hold across worker replicas and restarts; asset concurrency is a throughput tuning knob, and a few extra connections when two workers run is not a correctness problem.

**Backpressure.** If the asset queue grows beyond a threshold (say 10,000 pending), page workers slow down rather than racing ahead. Otherwise a fast page crawl over an image-heavy catalogue builds a queue that outlives the run by hours.

**A third pool: rendered pages.** Playwright contexts are expensive enough (\~300 MB each, 2–5 s per page) that they cannot share the static page pool's sizing. They get their own bounded pool, capped at 3 concurrent contexts, with each context recycled every 50 pages to contain memory growth.

The per-domain politeness gate is unchanged — a rendered fetch claims the same `domains.next_eligible_at` lock as a static one, so a domain is still fetched one page at a time whichever adapter serves it. Only the pool sizing differs. Both adapters sit behind one `Fetcher` port and are selected by the domain's `render_mode` flag (`static` | `rendered` | `auto`), so the scheduler neither knows nor cares which one ran.

`auto` is worth having from the start: fetch statically, and if the template's required fields fail to resolve but the page returned 200, re-fetch once through the browser and record which path succeeded. After a few runs the flag can be pinned per domain from observed behaviour rather than guessed at onboarding. The cost of a wrong guess is then one wasted static fetch, not a silently empty extraction.

Block images, fonts, and media in the browser context via route interception — the asset pool downloads images separately, so rendering them twice is pure waste and typically halves render time.

### Rules

- **Default delay** 2000 ms, jittered ±30% so request timing is not machine-regular.
- **Concurrency per domain** defaults to 1. Raise it only for domains you know tolerate it.
- **robots.txt** fetched once per domain per run, cached; `Crawl-delay` raises `crawl_delay_ms` if higher than the configured value, never lowers it.
- **Backoff.** HTTP 429 or 503 → exponential backoff on that domain (2×, capped at 15 minutes), `consecutive_failures` incremented. Three consecutive 403s → domain auto-paused and surfaced in the UI. Getting blocked should stop the crawler, not be retried through.
- **Identification.** A real, descriptive User-Agent with contact information. Pretending to be Chrome is both less honest and, in practice, more likely to be fingerprinted and blocked.
- **Asset fetches bypass the page gate** and run on their own pool with their own per-host cap — see the concurrency model above. They are still rate-limited, just far less strictly than HTML fetches.
- **Conditional requests.** Store `ETag` and `Last-Modified`; send `If-None-Match` on re-crawls. A 304 is a free observation and a visible courtesy to the origin.

## Local LLM integration

The model is invoked **once per template**, not once per page. That single fact removes almost all performance pressure and lets you run a larger, more capable model than a per-page design would allow.

### Setup

- `llama-server` running natively on macOS with Metal, bound to `127.0.0.1:8080`.
- A 30B-class instruction-tuned model; the Ultra's unified memory accommodates it comfortably. Quality of selector proposals matters far more than tokens per second here.
- The application talks to it over HTTP behind an `LLMClient` port. Swapping models, or swapping to a hosted API for comparison, touches one adapter.

### The proposal task

Input to the model is deliberately *not* raw HTML — a product page is often 500 KB of markup and scripts, most of it irrelevant and expensive to attend to. Preprocess first:

1. Strip `<script>`, `<style>`, comments, SVG bodies.
2. Collapse the DOM to a skeleton: tag, `id`, `class`, and truncated text content per node.
3. Keep nodes with visible text or `src`/`href` attributes; drop empty wrappers.
4. Cap at a few thousand nodes, prioritising the main content region.

The prompt asks for a strict JSON response: a CSS selector per requested field, a confidence score, and the text it believes that selector resolves to. **The proposal is then verified deterministically** — the application runs each proposed selector against the real DOM and compares the result to what the model claimed. A selector that does not resolve, or resolves to something different, is discarded before you ever see it.

This verification step matters more than the model choice. It converts a probabilistic suggestion into a checked candidate, and it means a weak proposal fails loudly rather than producing plausible-looking wrong data.

### What the model does not do

- It does not extract field values at crawl time.
- It does not decide whether a domain goes active — you do.
- It does not run during a crawl run at all, only during onboarding and review.

## Image pipeline

Resize on download, discard originals, deduplicate by content hash.

### Flow

1. Product page yields image URLs, resolved to absolute.
2. Enqueue onto the asset pool, which runs in parallel with page crawling and permits several concurrent fetches per host.
3. Hash the fetched bytes. If the hash exists in `assets`, link the observation to the existing asset and stop — no decode, no write.
4. Decode with Pillow, resize to fit the configured box (default 1200×1200), **downscale only** — an image already smaller is stored as-is.
5. Encode as WebP quality 82, with a JPEG fallback for anything that fails.
6. Write to `/data/assets/<hash[0:2]>/<hash[2:4]>/<hash>.webp` and insert the `assets` row.

### Why these choices

- **Hash before decode.** Decoding is the expensive step; most re-crawls return identical bytes. Hashing first makes a repeat crawl nearly free on the image path.
- **Two-level directory sharding.** A flat directory with hundreds of thousands of files degrades on every filesystem. Two hex levels gives 65,536 buckets.
- **Content-addressed paths.** The same product image used across several pages is stored once, and the path is derivable from the hash without a database lookup.
- **Originals discarded** per your requirement. If you later want a different box size, you re-crawl — which is why the box should be set generously once rather than tuned often.

### Scale note

At your actual onboarding pace (2–3 domains at a time) this is small. At the 1200-domain end state, assume roughly 20,000 products × 6 images × \~150 KB post-resize ≈ 18 GB, with deduplication typically removing 10–20% of that. Budget disk accordingly but do not over-engineer for it now.

## Change tracking

Every crawl writes a `page_observations` row. Current state is the `page_current` view. Nothing is updated in place.

### Suppressing noise

A naive append-only design fills with identical rows. Two guards:

- **`content_hash`** over the normalised extracted fields (not the raw HTML, which changes on every request due to timestamps and session tokens). If the hash matches the previous observation, write a lightweight row recording only `observed_at` and `http_status`, with extracted fields null and a `unchanged` flag — or skip entirely and bump `pages.last_crawled_at`, configurable per domain.
- **Field-level diffing** computed at read time, not stored. A `price_history` view over observations where `price_amount` differs from the prior row gives you the change series without a second table.

### Example queries

```sql
-- Price changes for one product, oldest first
SELECT observed_at, price_amount, price_currency
FROM page_observations
WHERE page_id = $1 AND price_amount IS NOT NULL
ORDER BY observed_at;

-- Products whose price moved in the last run
SELECT p.url, prev.price_amount AS was, cur.price_amount AS now
FROM page_current cur
JOIN pages p ON p.id = cur.page_id
JOIN LATERAL (
  SELECT price_amount FROM page_observations o
  WHERE o.page_id = cur.page_id AND o.observed_at < cur.observed_at
    AND o.price_amount IS NOT NULL
  ORDER BY o.observed_at DESC LIMIT 1
) prev ON TRUE
WHERE cur.price_amount IS DISTINCT FROM prev.price_amount;

-- Pages that stopped extracting cleanly (silent breakage detector)
SELECT d.host, count(*) AS failing
FROM page_current c
JOIN pages p ON p.id = c.page_id
JOIN domains d ON d.id = p.domain_id
WHERE c.validation ? 'failed'
GROUP BY d.host ORDER BY failing DESC;
```

### Retention

Observations are kept indefinitely — they are small and they are the point of the system. Only `raw_html_path` files are purged, on a 7-day TTL, by a sweep that runs at the start of each run (`DELETE` the files, null the column). No separate cron needed.

## API and UI

FastAPI backend with Pydantic schemas, React + TypeScript + Tailwind frontend, served as static files from the same container in production.

### Views

| View | Purpose | Notes |
| --- | --- | --- |
| Domains | List, state, template count, last run, health | The home screen |
| Seed | Add a URL, or upload a CSV against the fixed template | Validates and previews before enqueueing |
| **Template review** | Approve/reject proposed selectors against a live preview | The screen you will use most — build it properly |
| Run monitor | In-flight runs, per-domain progress, live log | SSE-driven |
| Runs history | Completed runs, counts, duration, failure summary | Links into reports |
| Unknown pages | Review inbox for pages that failed | Trigger a new LLM proposal from here |
| Products | Browse extracted data, filter by domain/category | Includes observation history per page |
| Reports | Validation failures, changed prices, broken templates | Per run and across runs |

### Live progress via SSE

```
GET /api/runs/{run_id}/events   ->  text/event-stream

event: progress
data: {"domain":"example.com","queued":412,"done":180,"failed":3}

event: page
data: {"url":"...","status":200,"strategy":"selector","fields":7}

event: domain_state
data: {"domain":"example.com","state":"broken","reason":"validation_rate"}
```

SSE rather than WebSockets: progress streaming is one-directional, SSE reconnects natively with `Last-Event-ID`, and it needs no additional protocol handling on either side. Control actions (pause, stop) go through ordinary `POST` endpoints.

### API surface

```
POST   /api/domains                 register a domain
PATCH  /api/domains/{id}            state, delay, render_mode, robots override
POST   /api/seeds                   single URL
POST   /api/seeds/csv               CSV upload
GET    /api/templates?domain_id=    list, all versions
POST   /api/templates/{id}/propose  request an LLM proposal
POST   /api/templates/{id}/test     run selectors against sample URLs
POST   /api/templates/{id}/approve  promote to active
POST   /api/runs                    start a run over selected domains
POST   /api/runs/{id}/stop          halt gracefully
GET    /api/runs/{id}/events        SSE progress
GET    /api/unknown-pages           review inbox
GET    /api/pages                   browse extracted data
GET    /api/reports/{kind}          validation, changes, health
```

## Brand and design system

**Spydra** — a crawler that sits quietly at the centre of a web and feels every thread. The name does the work; the interface should not try to reinforce it with atmosphere. Nothing here is a terminal, nothing glows, nothing is green on black.

The design target is **a professional instrument**: the visual register of a modern analytics or infrastructure console, where restraint signals competence. Colour is reserved almost entirely for state, so when something turns amber or red it reads instantly rather than competing with decoration.

### Logo

*Concept:* a spider at rest on a web whose nodes are computers.

**Construction**

- **The web** — not a decorative spiral but a **network topology**: four to six radial strands from a centre, two or three concentric connecting arcs, drawn as hairlines. Each vertex terminates in a small geometric monitor or node glyph (a rounded rectangle with a one-unit stand, or a simple filled dot at small sizes). The web is the infrastructure; the strands are connections.
- **The spider** — geometric, not naturalistic. Two circles for cephalothorax and abdomen on the vertical axis, eight legs as four mirrored pairs of two-segment strokes at roughly 40–50°, with a slight downward bend at the joint. Symmetrical, calm, centred on the web. It is a weaver and a sensor, not a threat — no fangs, no eyes, no hair.
- **Geometry** — 24×24 base grid, 1.5-unit stroke, rounded caps and joins. Everything derives from circles and straight segments so it stays crisp when scaled.

**Variants** (build all five before the UI, because retrofitting a favicon from a detailed mark never works):

| Variant | Use | Detail level |
| --- | --- | --- |
| Horizontal lockup | App header, documents | Mark + wordmark, clear space = one cap height |
| Stacked lockup | Login, splash, print | Mark above wordmark |
| Mark only | Sidebar collapsed, avatars | Full web + spider |
| Favicon / 16–24px | Browser tab, OS | **Spider only** — web strands drop out entirely below 24px |
| Monochrome | Watermark, single-colour print | One weight, no fills |

**Minimum sizes:** lockup 120px wide, mark 32px, favicon variant below that.

**Avoid:** gradients inside the spider, drop shadows, anything photoreal, and the horror register (red eyes, dark backgrounds, dripping anything). The mark should be at home next to a Datadog or Grafana logo, not on a Halloween poster.

### Colour

**Light is the default theme.** A persistent toggle sits in the top bar; on first visit the app respects `prefers-color-scheme`, and once the user chooses, that choice is stored and wins thereafter.

One brand hue, a wide neutral scale, and six semantic state colours. Brand colour is used for primary actions and active navigation only — never for data, never for state.

```css
:root {
  /* Brand — deep indigo. Used for actions and focus, not for information. */
  --brand-50:  #EEF0FB;
  --brand-500: #4F56D9;
  --brand-600: #4338CA;   /* primary buttons, active nav */
  --brand-700: #3730A3;   /* hover */

  /* Surfaces — light default */
  --bg-base:    #F7F8FA;  /* app background */
  --bg-surface: #FFFFFF;  /* cards, tables, panels */
  --bg-subtle:  #F1F3F6;  /* table header, hover rows */
  --border:     #E3E6EB;
  --border-strong: #CDD2DA;

  /* Text */
  --text-primary:   #16191F;
  --text-secondary: #5A616D;
  --text-muted:     #878E9A;

  /* Domain lifecycle — the only place colour carries meaning */
  --state-discovered: #6B7280;  /* grey   — known, untouched */
  --state-pending:    #B45309;  /* amber  — needs you */
  --state-active:     #047857;  /* green  — healthy */
  --state-broken:     #B91C1C;  /* red    — failing */
  --state-paused:     #C2410C;  /* orange — stopped deliberately */
  --state-archived:   #9CA3AF;  /* faded  — retired */
}

:root[data-theme="dark"] {
  --bg-base:    #0F1115;
  --bg-surface: #171A21;
  --bg-subtle:  #1E222B;
  --border:     #272C36;
  --border-strong: #39404D;
  --text-primary:   #E8EAEE;
  --text-secondary: #A2A9B6;
  --text-muted:     #6E7684;
  /* State colours lighten for contrast; hues are unchanged so the
     mapping a user learns in one theme still holds in the other. */
  --state-pending: #F59E0B;
  --state-active:  #34D399;
  --state-broken:  #F87171;
  --state-paused:  #FB923C;
}
```

Exposed to Tailwind v4 as semantic utilities (`bg-surface`, `text-ink-muted`, `text-state-broken`) by `design/tokens/tailwind-theme.css`; the tokens themselves are `--sp-*` prefixed to avoid a Tailwind namespace collision (ADR-0018). **No raw colour classes in components** — `text-red-600` in a component is a bug, because the state-to-colour mapping must be changeable in one file and must stay identical across both themes.

Both themes are checked against WCAG AA for body text and AAA for the state pills, since those are the elements you will read fastest and most often.

### Typography

| Role | Face | Notes |
| --- | --- | --- |
| UI | **Inter** (variable) | Neutral, excellent at 13–14px, true tabular figures |
| Data / code | **JetBrains Mono** | Selectors, URLs, JSON, log lines |
| Wordmark | **Space Grotesk**, medium, −2% tracking | Logo only — never in the interface |

Self-host both families rather than using the Google Fonts CDN: this is a local tool that should work with the network down, and the request would be the only outbound call the UI makes.

**Scale** — base 14px, because this is a dense operational interface and 16px wastes a third of every table row.

```
11px / 16  — table micro-labels, badge text, uppercase +0.04em
12px / 18  — secondary metadata, timestamps, helper text
13px / 20  — table body, dense lists
14px / 22  — body default, form inputs
16px / 24  — card titles, section intros
20px / 28  — screen headings
28px / 36  — page titles (sparing)
```

**Weights:** 400 body, 500 for table headers and labels, 600 for headings and emphasis. Nothing lighter than 400, nothing heavier than 600.

**Rules that matter in this UI specifically:**

- `font-variant-numeric: tabular-nums` on **every** numeric column — counts, prices, durations, percentages. SSE updates land continuously and non-tabular digits make the whole table shiver.
- Monospace for every selector, URL, and field value in the review screen. A CSS selector in a proportional face is genuinely harder to read character by character, and character-level reading is exactly what you are doing there.
- URLs truncate in the middle, not the end — the path tail is the distinguishing part.
- Numbers and identifiers never wrap; long text clamps to two lines with a tooltip.

### Form and spacing

- **4px base unit**; component padding on an 8px rhythm. Table rows 36px (comfortable) or 28px (compact, user-toggleable and persisted).
- **Radius:** 6px controls and inputs, 8px cards and panels, 4px badges, full-round only on status dots.
- **Borders over shadows.** A 1px `--border` separates surfaces; elevation is reserved for genuinely floating things — dropdowns, popovers, the one modal. Flat, bordered surfaces read as precise; drop shadows everywhere read as a consumer app.
- **Focus:** 2px `--brand-500` ring with a 2px offset, on every interactive element. You will operate the review screen from the keyboard more than the mouse.
- **Motion:** 120–160ms ease-out on state changes, none on data updates. A row whose value just changed gets a single 400ms background flash, then settles. Nothing slides, nothing bounces.

### Anti-patterns

Worth naming explicitly, since crawler tooling drifts toward them by default:

- Terminal aesthetics — monospace everywhere, green-on-black, ASCII borders, fake scanlines
- Neon accents, glow effects, glassmorphism, animated gradient backgrounds
- Dark-mode-only, or a dark mode that is simply the light theme inverted
- Decorative spider webs in the chrome. The logo carries the metaphor; the interface does not repeat it
- Colour used for emphasis rather than meaning — if everything is coloured, the one red row stops registering

## Screens

Nine screens. The table above is the index; this section is the specification — what each screen is for, what it contains, and which widgets are shared.

One principle runs through all of them: **this is a single-operator control room, not a consumer app.** Density beats whitespace, every list is filterable, and every state is visible without drilling in. You are the only user and you will be looking for problems, so the screens should surface anomalies rather than celebrate successes.

### App shell

Persistent left sidebar, content area to the right. No modals for anything that takes longer than a second — long operations get their own route so a refresh does not lose them.

**Sidebar** — fixed 240px, collapsible to icons:

- Nav: Domains · Seeds · Templates · Runs · Unknown Pages · Products · Reports
- Two live badges, both SSE-fed: *pending reviews* (amber, count of templates awaiting approval) and *active run* (green pulse with page counter, or dormant)
- Footer: llama-server reachability dot, Postgres dot, free disk on `/data`

The badges exist because the two things that silently stall this system are an unreviewed template queue and a dead llama-server. Both should be visible from every screen without navigating.

**Top bar** — breadcrumb, global search (domain host or product URL), and a **Start Run** button that is enabled only when at least one domain is `active`.

### Shared widgets

Build these once; every screen composes them.

| Widget | Used by | Behaviour |
| --- | --- | --- |
| `<DomainStatePill>` | Domains, Runs, Unknown | Colour-coded lifecycle state with tooltip explaining why it is in that state |
| `<SelectorField>` | Template review, Unknown | Editable CSS selector + live-resolved value + match count; red when it resolves to nothing, amber when it resolves to several |
| `<PagePreview>` | Template review, Unknown, Products | Sanitised HTML in a sandboxed iframe with the active selector's match outlined |
| `<ValidationBadge>` | Products, Reports, Runs | Per-field pass/fail with the failing rule named |
| `<ProgressBar>` | Run monitor, Domain detail | Queued / in-flight / done / failed as a stacked bar, not a percentage |
| `<ObservationTimeline>` | Products, Reports | Horizontal time series of observations with change points marked |
| `<DataTable>` | Every list screen | Server-side pagination, column filters, URL-encoded state so views are linkable |

`<DataTable>` keeping filter state in the URL matters more than it sounds: when a run surfaces 40 broken pages, you want to send yourself that exact filtered view, not reconstruct it.

### 1. Domains — the home screen

The operational overview. Answers "what is set up, what is healthy, what needs me."

**Layout:** summary strip across the top, filterable table below.

*Summary strip* — six counters, each a filter link into the table: Active · Awaiting review · Broken · Paused · Never crawled · Total pages extracted.

*Table columns:* Host · State pill · Templates (count, with a badge if any are unapproved) · Pages known · Last crawled · Extraction health (7-day rolling % of pages passing validation, as a sparkline) · Crawl delay · Render mode (static/rendered icon) · Actions.

*Row actions:* Pause · Resume · Edit settings · View templates · Crawl now (single domain).

**Sort by extraction health ascending as the default.** The healthy domains need nothing from you; the degrading ones are the reason you opened the screen. A domain sliding from 98% to 71% over a week is the single most valuable signal this system produces, and it should be the first thing on screen.

*Bulk actions:* select rows → pause, resume, set delay, start a run over the selection.

### 2. Domain detail

One domain, everything about it. Four tabs.

- **Overview** — settings form (crawl delay, per-host asset concurrency, render mode, max depth, URL caps, deny patterns, user-agent override), plus robots.txt as fetched with any `Crawl-delay` directive highlighted and a note on whether it overrode your configured value.
- **Templates** — every template version for this domain, with URL pattern, field count, active flag, created date, and approval author. Diff view between any two versions, which is what you reach for when extraction breaks after a redesign.
- **Pages** — all known URLs for this domain with their last observation status; filter by validation state.
- **Activity** — chronological log: crawls, state transitions, backoff events, template approvals. This is your forensic trail when a domain gets blocked and you want to know what the crawler did in the preceding hour.

### 3. Seeds — intake

Two modes on one screen, sharing a preview panel.

**Single URL:** paste a URL → the app resolves the host, shows whether the domain already exists and in what state, and lets you set depth, URL pattern scope, and whether this seed is a listing page or a direct product URL.

**CSV upload:** drag-and-drop against a fixed template. The columns should be `url, domain_hint, category, max_depth, notes`.

*The preview step is not optional.* After parsing, show a table of parsed rows with per-row validation — malformed URL, duplicate of an existing seed, host already paused, depth above the cap — and a count of how many would be accepted. Nothing enqueues until you confirm.

*Downloadable template CSV* from this screen, and a persistent note of which columns are required. You will use this a handful of times a month and will not remember the format.

After confirmation: new domains enter `discovered` and are routed straight to template proposal; known-active domains enqueue immediately.

### 4. Template review — the critical screen

**This is the bottleneck made visible.** You will spend more time here than on every other screen combined, and its design determines whether 1200 domains is achievable or not. Build it properly even in phase 3, when it only holds hand-written selectors.

**Three-pane layout:**

*Left (45%) — page preview.* Sanitised HTML in a sandboxed iframe. Hovering a selector on the right outlines every element it matches, in place. A toggle switches to raw-DOM-skeleton view, which is what the model actually saw — useful when a proposal is wrong and you want to know whether the model was misled or just mistaken.

*Centre (35%) — field list.* One `<SelectorField>` per requested field (title, price, description, images, category, vendor, supplier, specs table). Each row shows: field name · proposed selector (editable) · **resolved value on this page** · match count · model confidence. Edits re-resolve on a 300 ms debounce against the already-loaded DOM, with no network round-trip.

*Right (20%) — sample strip.* Three to five URLs from the same pattern. Each shows a per-field pass/fail grid for the current selector set.

**The sample strip is the feature that makes this screen worth building.** A selector that works on the page you are looking at and fails on the next product is the single most common error, and it is invisible in a one-page review. The grid should turn a cell red the moment a selector stops resolving on any sample, before you approve anything.

**Field-level controls:** required/optional toggle · validation rule picker (currency, non-empty, URL, integer, date) · transform chain (trim, strip currency symbol, resolve relative URL, take first match vs. all) · fallback selector.

**Discovery rules live on the same screen**, in their own section — `next_page` selector, `product_link` selector, `subcategory_link` selector, depth cap, and allow/deny URL patterns. A "dry-run discovery" button crawls one listing page and shows exactly which URLs would be enqueued, grouped by the rule that matched. This is where you catch a faceted-navigation trap before it generates 40,000 URLs, and it is far cheaper than catching it mid-run.

**Footer actions:** Reject (back to the inbox with a note) · Save draft · **Approve** (promotes the template to `is_active`, moves the domain to `active`, enqueues its seeds).

**Batch mode is built in, not an extension.** It ships with the review screen in phase 3.

A grid of up to 20 templates, each row collapsed to: domain · URL pattern · resolved value per field · sample pass/fail summary · confidence · approve / reject / open-full-review. One confirm applies the whole batch.

The single-template view and the batch grid are **two renderings of the same review state**, not two screens. Both read the same verified-proposal payload; the grid hides the preview pane and the per-field controls, and "open full review" expands a row in place. Building it this way costs little now and avoids the usual outcome, where the batch screen drifts from the detailed one and starts approving against stale data.

Why build it before the backlog demands it: retrofitting a grid around a screen designed for one template at a time means reworking the state management, not adding a view. At 2–3 domains a week you will not need it; at the point you do need it, you will need it urgently and will not want to be refactoring.

### 5. Unknown pages — the review inbox

Pages that could not be understood. Your work queue, as you specified.

**Grouped, not listed.** A flat list of 400 failed pages is useless; the same root cause usually produces dozens. Group by `(domain, failure_reason, url_pattern)` so one fix clears the whole group.

*Failure reasons, each with its own remedy path:*

| Reason | What it means | Action offered |
| --- | --- | --- |
| `no_template` | No template matches this URL pattern | Propose a template |
| `validation_failed` | Selectors resolved but values failed their rules | Open in template review with this page loaded |
| `fetch_error` | Non-2xx or timeout | Retry, or inspect the response |
| `empty_extraction` | Selectors matched nothing at all | Usually a redesign — diff against the last working observation |
| `llm_low_confidence` | Proposal produced but below threshold | Review manually |

*Row expansion* shows the stored HTML snapshot (while within the 7-day TTL), the template that was attempted, and the per-field failure detail.

**Bulk actions:** propose templates for a whole group · retry a group · dismiss as not-a-product-page (which adds a deny pattern to the domain, so it stops recurring).

The dismiss-as-deny-pattern path matters: without it, the same non-product URLs reappear in this inbox every run and it slowly becomes noise you stop reading.

### 6. Run monitor — live

SSE-driven. What is happening right now.

**Header:** run ID, elapsed time, Pause / Stop buttons, and an overall `<ProgressBar>` showing queued / in-flight / done / failed as a stacked bar rather than a percentage. A percentage lies during discovery, because the denominator is still growing.

**Per-domain cards**, one per domain in the run, each showing: host · state pill · its own stacked progress bar · pages/min · current delay (with a flag if backoff has raised it) · error count · next-eligible countdown. A domain that has been auto-paused goes red and sorts to the top.

**Two separate throughput graphs** — pages/min and assets/min, plotted together on a shared time axis. They should look different, and seeing them diverge is how you confirm the two pools are working: a flat page line with a busy asset line is normal after discovery finishes, while the reverse means the asset pool is starved or the host is throttling.

**Live log pane** — scrolling event feed from the SSE stream, filterable by level and domain, pausable. Each line: timestamp · domain · URL · status · extraction strategy that won (structured / selector / failed) · field count.

**Asset pool panel** — queue depth, in-flight count, per-host concurrency in use, dedupe hit rate. Queue depth climbing steadily is the backpressure signal described in the concurrency model, and it belongs on screen rather than in a log.

**Reconnection is non-negotiable.** The browser will sleep, you will close the laptop. SSE reconnects with `Last-Event-ID` and the UI backfills from the run's event log rather than showing a gap or, worse, a frozen bar that looks like a stall.

### 7. Runs history

Completed runs, newest first. Each row: run ID · started/duration · domains covered · pages crawled · pages changed · new pages · failures · assets downloaded · bytes.

*Run detail* expands to per-domain breakdown, the validation summary, a link to the pages that failed in that run, and a diff against the previous run of the same domain set — which is the view that answers "did this redesign break us, or did we always have 12% failures here."

*Comparison mode:* select two runs → side-by-side counts and a list of domains whose health moved materially.

### 8. Products — data browser

Browse what was extracted. Filters: domain · category · validation state · last-seen window · price range · has-images · free-text over title and description.

*Table view* for scanning, *card view* with image thumbnails for visual verification — the fastest way to spot that a selector has started picking up a placeholder or a related-product image.

**Product detail** is where change tracking surfaces:

- Current extracted fields with `<ValidationBadge>` per field
- `<ObservationTimeline>` across all observations, with change points marked
- Price history chart, which is the obvious reason you asked for change tracking
- Field-level diff between any two observations
- The image set, with dedupe indication where an asset is shared with other pages
- Source URL, the template version used, and the raw HTML snapshot while it is still within TTL

Showing **which template version** produced each observation is what lets you attribute a data change to a site change rather than to your own edit. Without it, a price history containing your own selector mistake is indistinguishable from a real price move.

### 9. Reports

Standing reports rather than ad-hoc querying. Each is a saved view with CSV and JSON export.

- **Extraction health** — pass rate by domain and by field, trended over runs. The entry point for finding silent breakage.
- **Broken templates** — domains over the 20% failure threshold, with the first run where the rate moved and the field that degraded first.
- **Price changes** — every change in a window, filterable by magnitude so you can ignore ±1% noise.
- **New and disappeared products** — appeared in this run, or absent for N consecutive runs.
- **Crawl politeness** — requests per domain per run, 429/403 counts, average effective delay. Your evidence that the crawler is behaving, and the first place to look after a block.
- **Coverage** — domains onboarded, templates approved, unknown-page backlog over time. The honest measure of whether you are gaining or losing ground against the 1200-domain target.

The coverage report is the one to build last and read most. Onboarding pace against backlog growth is the number that tells you whether the batch-review and template-inheritance mitigations are needed yet, or still just options.

## Deployment

Three containers plus one host process. The host process is the important detail.

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: crawler
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s

  api:
    build: ./backend
    depends_on:
      db: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql://postgres@db:5432/crawler
      LLM_BASE_URL: http://host.docker.internal:8080   # host-side llama-server
      ASSET_ROOT: /data/assets
      HTML_CACHE_ROOT: /data/html
    volumes:
      - /Users/you/crawler-data:/data        # bind mount, not a volume
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports: ["8000:8000"]

  worker:
    build: ./backend
    command: python -m crawler.worker
    depends_on:
      db: { condition: service_healthy }
    environment: *api-env
    volumes:
      - /Users/you/crawler-data:/data
    deploy:
      replicas: 2        # scale to taste; politeness is enforced in the DB

volumes:
  pgdata:
```

### On the host, not in Docker

```bash
llama-server -m ~/models/<model>.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 16384 --n-gpu-layers 999
```

**Why:** Docker Desktop on macOS has no Metal GPU passthrough. A containerised model runs on CPU inside the VM and loses most of the Ultra's advantage. Keep it native.

### Storage decisions

- **Bind mount, not a named volume**, for `/data`. You want images and HTML visible in Finder, backed up by Time Machine, and survivable across a `docker compose down -v`.
- **Named volume for Postgres** — it should not be casually browsable, and its performance is better on a volume than a macOS bind mount.
- **Workers scale by replica count.** Because politeness state lives in Postgres, adding workers never violates per-domain limits. This is a direct benefit of rejecting the broker.

### Project layout

```
backend/
  crawler/
    domain/          # entities, value objects — no I/O
    ports/           # Frontier, Fetcher, Extractor, LLMClient, AssetStore
    adapters/
      postgres/      # FrontierRepo, PageRepo, TemplateRepo
      http/          # HttpxFetcher, PlaywrightFetcher
      llm/           # LlamaServerClient
      storage/       # LocalAssetStore
    extraction/
      strategies/    # structured.py, selector.py, llm_proposal.py
      chain.py       # ordered strategy chain
      validation.py
    scheduler/       # politeness gate, claim loop
    api/             # FastAPI routers, schemas, SSE
    worker.py
frontend/
  src/{components,views,api,hooks}
```

The `ports/` + `adapters/` split is what makes the Postgres-over-Kafka decision reversible, keeps Playwright out of the default path, and lets extraction strategies be added without touching the chain that orders them — dependency inversion and open/closed, applied where they actually earn their cost rather than everywhere.

## Failure modes

| Failure | Detection | Response |
| --- | --- | --- |
| Blocked by a site (403/429) | HTTP status, per-domain failure counter | Exponential backoff; 3 consecutive 403s auto-pauses the domain and raises it in the UI. Never retry through a block. |
| Selector silently breaks after a redesign | Per-field validation on every observation | Page routed to `unknown_pages`; domain marked `broken` once failures exceed 20% of a run |
| Infinite URL space (faceted nav, calendars) | Run-level URL cap, depth cap | Run halts for that domain, reports the pattern that exploded; you add a `deny_pattern` and re-approve |
| Worker crashes mid-page | `locked_until` expiry on the queue row | Row returns to `pending` after 120 s; `attempts` increments; 3 attempts moves it to `failed` |
| Postgres unavailable | Health check, connection errors | Workers exit cleanly; run resumes from the queue on restart. No state lives only in memory |
| llama-server down | Connection refused on proposal | Onboarding blocks with a clear message; **crawling is unaffected**, since the model is not in the crawl path |
| Disk fills (assets or HTML) | Pre-run free-space check | Run refuses to start below a threshold; HTML purge sweep runs first |
| Duplicate crawls on restart | `UNIQUE (run_id, url_hash)` plus transactional dequeue | Structurally prevented, not retried away |
| Playwright memory growth | Context recycling after N pages | Contexts restarted every 50 pages; pool capped at 3 |
| Bad LLM proposal | Deterministic verification against the real DOM | Discarded before review; never reaches stored data |

### The two that actually matter

**Getting blocked** is handled by the politeness gate plus aggressive auto-pausing. The design choice worth restating: on a 403, the system stops rather than retries. A retry loop against a site that has decided to block you is how a temporary block becomes a permanent one.

**Silent extraction failure** is handled by validation rules and the review inbox. This is the failure that produces no error and corrupts your dataset quietly — the reason validation is mandatory per field rather than optional.

## Build plan

Five phases. Each ends with something you can run end to end. Resist building the LLM layer early — it is the most interesting part and the least load-bearing.

### Phase 1 — Crawl one domain, both fetch paths, hand-written template

No UI, no model. Postgres schema, the politeness gate, `httpx` and Playwright fetchers behind one Fetcher port, selector-based extraction, observation writes. A YAML file holds the template, including its render mode. Success: one static domain and one JS-rendered domain both crawled politely end to end, data in Postgres.

This phase proves the scheduler and the data model, which are the two things most expensive to get wrong.

### Phase 2 — Discovery and the queue

Listing-page discovery with depth, pattern filters, canonicalisation, dedupe, and the run-level cap. Seeds from CSV. Success: a category seed yields a full product set without wandering off-site or exploding on facets.

### Phase 3 — UI, runs, and review

FastAPI endpoints, React shell, domain list, run monitor with SSE, products browser. Template editing and testing against sample URLs — still hand-authored selectors, but now edited in the UI rather than a file. The review screen ships with both renderings — single and batch — from the start. Success: you can onboard a domain without touching the filesystem.

### Phase 4 — LLM proposals and the review loop

llama-server integration, DOM skeletonisation, proposal prompt, deterministic verification, the review screen, the unknown-pages inbox. Success: a new domain goes from seed URL to approved template without you writing a selector by hand.

### Phase 5 — Assets, validation, reports, and render hardening

Image pipeline with resize and dedupe. Per-field validation rules and the broken-template detector. Reports. Hardening of the rendered path — context pooling, recycling, memory caps, and per-domain `render_mode` overrides — tuned now that you know which sites actually need it and how many.

### Sequencing rationale

The order follows risk, not interest. Phases 1 and 2 contain everything that is hard to change later: the queue semantics, the politeness model, URL canonicalisation, the observation schema. Phases 4 and 5 are additive — they slot into ports that already exist.

A common failure mode for a project like this is to build the model integration first because it is the novel part, then discover the scheduler cannot support it. The strategy chain and the `LLMClient` port are designed so phase 4 adds a rung and an adapter, nothing more.

## Risks and open questions

### The dominant risk is your attention, not the technology

At roughly one template per domain and bespoke sites that mostly will not emit JSON-LD, 1200 domains implies several hundred review sessions. The architecture handles it; the calendar is the constraint. Three mitigations, in order of effectiveness:

1. **Batch review UI** (built in from phase 3) — approve 20 templates at a time with resolved values shown side by side. Turns \~2 minutes per template into \~15 seconds.
2. **Template inheritance** — hedged, not built. Your expectation is that the domains are bespoke and inheritance will not be needed. The hedge is therefore a single nullable parent\_template\_id column in the schema and nothing else: no resolution logic, no UI, no merge semantics until a real case appears. A column costs one migration line; a resolution layer nobody uses costs every future change to template handling.
3. **Tiered coverage** — hand-approve the domains that matter; run the long tail in best-effort LLM mode, flagged lower-confidence. Trades data quality for reach.

Decided: batch review is in from phase 3; inheritance is a column and no more; tiered coverage stays unbuilt until the coverage report shows the backlog growing faster than you clear it.

### Open questions

- **JS rendering prevalence.** No longer a gating question — rendering is supported from phase 1 regardless of volume. It remains worth measuring for sizing: the rendered pool caps at 3 concurrent contexts against 8–16 static workers, so if most domains need rendering your page throughput drops by roughly 4×. That changes run duration, not the design.
- **Supplier data shape.** "Vendor information, supplier details" may be structured tables on some sites and free prose on others. The JSONB column absorbs either, but if you need to query across suppliers consistently, a normalisation pass is a phase-5 addition worth scoping.
- **Legal posture.** Crawling bespoke supplier catalogues raises terms-of-service questions that are separate from the technical ones. Worth checking the ToS of your first few targets; I'm not giving legal advice here, only flagging that it's a real input to which domains you onboard.
- **Re-crawl cadence.** Currently manual. If change tracking becomes the primary use, a per-domain `recrawl_interval` column and a cron trigger is a small addition — the schema already supports it.

### Deferred deliberately

- Full-text search over descriptions (Postgres `tsvector` when needed).
- Export pipeline (the data is in Postgres; build the exporter when you know the target format).
- Proxy rotation. If you need it, the blocking problem has already happened and the polite-crawling assumptions need revisiting rather than patching.
