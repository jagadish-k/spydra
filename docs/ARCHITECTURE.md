# Spydra — architecture

Why the system is shaped the way it is: the scheduler, the politeness model,
the extraction chain and the failure modes. **This document holds intent.**
Anything with an exact shape — schema, routes, topology, screens — lives in
the spec that owns it:

| For                               | Read                                                             |
| --------------------------------- | ---------------------------------------------------------------- |
| Services, routing, data ownership | [`specs/010-service-topology.md`](specs/010-service-topology.md) |
| Schema                            | [`specs/001-domain-model.md`](specs/001-domain-model.md)         |
| HTTP API and SSE                  | [`specs/005-api.md`](specs/005-api.md)                           |
| Screens                           | [`SCREENS.md`](SCREENS.md) · mockups in `design/mockups/`        |
| Visual language                   | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) · [`BRAND.md`](BRAND.md)  |
| Running it                        | [`DEVELOPMENT.md`](DEVELOPMENT.md)                               |
| What to build next                | [`BUILD_PLAN.md`](BUILD_PLAN.md)                                 |

Decisions are recorded in [`adr/`](adr/README.md), each with its stated cost.
Where this document and a spec disagree, the spec is more specific and wins
on detail; this one wins on intent.

## Overview and scope

A single-user, locally-hosted crawler that discovers and extracts structured product data from bespoke e-commerce and supplier sites, using a local LLM to propose extraction rules that the operator approves before any domain goes live.

The system is deliberately a **single application with an embedded datastore**, not a distributed one. Every constraint below points away from the usual web-scale crawler architecture.

| Constraint    | Value                                                   | Architectural consequence                                           |
| ------------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| Users         | One (the operator), local only                          | No auth, no multi-tenancy, no horizontal scaling                    |
| Domains       | 2–3 onboarded at a time, growing toward \~1200          | Onboarding loop is the primary interface; crawling is the batch job |
| Worst failure | Being blocked by a remote site                          | Politeness is a correctness requirement, not a nicety               |
| Seeds         | Category/listing pages, entered via UI or CSV           | Discovery layer required, with hard bounds                          |
| Crawl depth   | 5, following pagination, subcategories, product links   | Needs per-domain URL-pattern allowlists and a run-level URL cap     |
| Cadence       | Manual, infrequent                                      | No scheduler; no need for a long-running daemon                     |
| Extraction    | Operator-approved CSS/XPath per `(domain, url_pattern)` | Templates are versioned, first-class entities in Postgres           |
| Model role    | Propose selectors once per template; never per page     | Inference speed is near-irrelevant; model quality matters           |
| History       | Append-only observations, change tracking               | Observations table, not in-place updates                            |
| Host          | Mac Studio Ultra, Docker + host-side llama-server       | Unified memory allows a 30B-class model                             |

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
4. **Operational cost.** A broker is another process to run, monitor, and recover — on a single machine that was meant to run one standalone application.

**Hedge:** the queue sits behind a `Frontier` port with a Postgres adapter. If a single node is ever outgrown, that interface is the swap point. This costs nothing now and preserves the option.

### Structured data before selectors

Extraction runs as a strategy chain, cheapest rung first: JSON-LD/microdata → approved selectors → LLM proposal → unknown queue. Even on bespoke supplier sites where `schema.org/Product` coverage is thin, the free rung costs one parse attempt and occasionally eliminates a template entirely.

### Short-TTL raw HTML retention

No raw HTML is retained beyond a short window, and some retention is necessary because **versioned selectors without stored content give an audit trail nobody can act on** — "this selector was wrong" becomes "re-crawl the site," which is the stated worst failure mode. Gzipped HTML with a 7-day purge bounds the disk cost while covering the window in which extraction bugs actually surface.

### Append-only observations

Timestamps alone record _when_ a page was looked at, not _what changed_. Change tracking is a requirement, so every crawl writes an observation row; current state is a view over the latest per page. Retrofitting history onto an in-place-update schema means reconstructing data that was never captured.

### llama-server on the host, outside Docker

Docker Desktop on macOS runs a Linux VM with no Metal passthrough. A containerised model falls back to CPU and discards most of the Ultra's advantage. The model runs natively; the app container reaches it at `host.docker.internal`.

### Deferred by default

- **robots.txt is respected**, with a per-domain override flag set consciously, logged when used.
- **No scheduler.** Runs are operator-triggered. The `runs` table and queue support cron-driven triggering later with no schema change.

## The crawl pipeline

A run moves through three phases. All three share the same queue and the same politeness gate.

### 1. Seeding

Seeds enter from the UI as a single URL or a CSV upload. The CSV template is fixed: `url, domain_hint, page_kind, notes`. Each seed is canonicalised, assigned to a domain row (created in `discovered` state if new), and enqueued at depth 0.

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

**Fetch** uses async `httpx` by default. A domain flagged `render_mode = 'rendered'` is routed over HTTP to the render sidecar instead (ADR-0016). `auto` tries static first and falls back once. Mixed modes across domains in one run are supported, and the scheduler neither knows nor cares which adapter served a page.

**Extraction is a strategy chain.** Each rung is tried only if the previous one fails or is absent:

| Order | Strategy                                   | Cost                         | When it applies                                         |
| ----- | ------------------------------------------ | ---------------------------- | ------------------------------------------------------- |
| 1     | JSON-LD / microdata (`schema.org/Product`) | Free                         | Site emits structured data; most reliable where present |
| 2     | Approved template selectors                | Free                         | An active template matches the URL pattern              |
| 3     | LLM selector proposal                      | \~seconds, once per template | No template matches; result goes to review, not to data |
| 4     | Unknown queue                              | —                            | Nothing worked; the page is listed for review           |

Only rungs 1 and 2 produce stored observations. Rung 3 produces a _proposal_, which is why unapproved domains never generate data.

### Validation

Every extracted field is checked against its rule before the observation is written: `price` must parse as a currency amount, `title` must be non-empty, `images` must yield at least one resolvable URL. **No field is ever required** ([ADR-0027](adr/0027-no-required-fields.md)) — a per-field failure is recorded in `page_observations.validation` for the operator to read, and routes nothing. What routes is emptiness: a 200 response from which no field resolved lands in `unknown_pages` as `empty_extraction`, and once that exceeds 20% of a domain's pages in one run the domain is marked `broken` and the run for that domain halts. That is the redesign detector, and it is pointed at the signal that survives having nothing required.

This is the defence against a site redesign silently turning a working template into one that returns empty strings. Without it, you get a clean-looking run full of nulls.

## Domain lifecycle and the approval loop

Domain state is explicit, stored on the domain row, and it gates everything. A domain that is not `active` consumes no crawl budget and sends no requests — which is why a stalled review queue costs you nothing operationally, and why "block until I approve" is a cheap guarantee rather than an expensive one.

| State               | Meaning                                             | Crawls? | Exit                             |
| ------------------- | --------------------------------------------------- | ------- | -------------------------------- |
| `discovered`        | Seeded, nothing known about it                      | No      | A template proposal is requested |
| `awaiting_approval` | A proposal exists, verified, waiting on you         | No      | You approve or reject            |
| `active`            | At least one approved template                      | Yes     | You pause, or it breaks          |
| `broken`            | Validation failures exceeded threshold              | No      | Re-review the template           |
| `paused`            | You paused it, or 3 consecutive 403s auto-paused it | No      | You resume                       |
| `archived`          | Retired, data retained                              | No      | Terminal                         |

**The loop:** a seed enters → the domain is `discovered` → the crawler fetches one sample page per URL pattern (the only fetching an unapproved domain does, and it respects the same politeness gate) → the DOM is skeletonised and sent to the model → the proposal is verified deterministically against the real DOM → the domain moves to `awaiting_approval` → you review → approve promotes the template and moves the domain to `active`, which releases its seeds into the queue.

**Templates are versioned, never edited in place.** An approval creates a new row with an incremented version and flips `is_active`; the old version is retained. This is what makes a data change attributable: every observation records the template version that produced it, so a price that moved because the site changed is distinguishable from one that moved because you fixed a selector. Retrofitting that distinction later is impossible — the evidence is gone.

**A template is keyed on `(domain, url_pattern)`, not on domain alone.** A single site frequently needs different selectors for listing and product pages, and often per category section. Keying on the domain alone works until the first site that doesn't, and the migration at that point touches every row.

**Breaking is a state transition, not an error log.** When validation failures exceed 20% of a domain's pages in a run, the domain moves to `broken` and stops crawling mid-run. The alternative — carrying on and recording thousands of empty extractions — is how a redesign quietly corrupts a dataset.

**On inheritance.** `templates.parent_template_id` exists as a nullable self-reference from day one and is never populated. If a platform family does turn up, a child template overriding a parent's field map is an additive change to the extraction chain, and the existing rows are already shaped for it. Until then it is a column nothing reads — which is the correct cost for a possibility you do not expect to materialise.

## Politeness and scheduling

Being blocked is the worst outcome, so the scheduler is the component to get right. It is a **per-domain gate in front of a shared worker pool** — not a global semaphore and not a per-domain thread.

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

After each fetch the worker sets `domains.next_eligible_at = now() + crawl_delay_ms` (plus jitter). With 1,200 domains at a 2 s delay and 12 page workers, throughput is bounded by the pool, not by courtesy — the per-host constraint is nearly free once the domain count is high.

### Concurrency model

There are **two independent pools**, because HTML and assets have different risk profiles and different bottlenecks.

|                  | Page pool                      | Asset pool                        |
| ---------------- | ------------------------------ | --------------------------------- |
| Fetches          | HTML (listing + product pages) | Images                            |
| Workers          | 8–16 async tasks               | 16–32 async tasks                 |
| Per-host limit   | **1 concurrent**, 2 s gap      | **4–6 concurrent**, 200 ms gap    |
| Gated by         | `domains.next_eligible_at`     | `asset_hosts.semaphore`           |
| Blocked response | pause the domain               | pause assets only; pages continue |

Both pools run inside the same worker process, as two `asyncio.TaskGroup` loops over the same connection pool. They are separate queues, not separate services.

**Why assets may be parallelised within a host and pages may not.** A product page is a dynamic request: it hits application code, touches a database, costs the origin real CPU, and appears in their logs as a crawl pattern. An image is a static byte range, usually served from cache or a CDN edge, costing the origin almost nothing. Six concurrent image fetches is ordinary browser behaviour — a real browser opens exactly that many connections per host to render one page. One page request every two seconds plus bursty asset fetches is a traffic shape that looks like a visitor; sequential everything looks like a crawler.

The per-host asset cap still matters. Unbounded parallel fetching against one host is what trips rate limiters, and an image host that returns 429 must still back off — it is just that the backoff applies to the asset pool alone and does not stall page crawling.

**Pool sizing.** Page throughput is `min(workers, eligible_domains)`. With 2–3 domains active during onboarding there are 2–3 concurrent page fetches no matter how many workers run — that ceiling is the politeness requirement, not a bug. The asset pool is where parallelism actually pays, since images are typically 70–80% of total bytes and a single product page can yield six of them.

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

**A third pool: rendered pages.** Browser contexts are expensive enough (~300 MB each, 2–5 s per page) that they cannot share the static pool's sizing. They get their own bounded pool, capped at 3 concurrent contexts. Rendering runs in a sidecar service rather than in the worker process (ADR-0016), so the worker holds no browser and a Chromium crash cannot take the crawl down with it.

The per-domain politeness gate is unchanged — a rendered fetch claims the same `domains.next_eligible_at` lock as a static one, so a domain is still fetched one page at a time whichever adapter serves it. Only the pool sizing differs. Both adapters sit behind one `Fetcher` port and are selected by the domain's `render_mode` flag (`static` | `rendered` | `auto`), so the scheduler neither knows nor cares which one ran.

`auto` is worth having from the start: fetch statically, and if the extraction yields nothing usable on a 200, re-fetch once through the browser and record which path succeeded. (The condition was "the template's required fields fail to resolve"; [ADR-0027](adr/0027-no-required-fields.md) removed requiredness, so it is the `empty_extraction` predicate — otherwise `auto` could never fire.) After a few runs the flag can be pinned per domain from observed behaviour rather than guessed at onboarding. The cost of a wrong guess is then one wasted static fetch, not a silently empty extraction.

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

Input to the model is deliberately _not_ raw HTML — a product page is often 500 KB of markup and scripts, most of it irrelevant and expensive to attend to. Preprocess first:

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
- **Originals discarded** by design. If you later want a different box size, you re-crawl — which is why the box is set generously once rather than tuned often.

### Scale note

At the real onboarding pace (2–3 domains at a time) this is small. At the 1200-domain end state, assume roughly 20,000 products × 6 images × \~150 KB post-resize ≈ 18 GB, with deduplication typically removing 10–20% of that. Budget disk accordingly but do not over-engineer for it now.

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

## Failure modes

| Failure                                     | Detection                                              | Response                                                                                                             |
| ------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Blocked by a site (403/429)                 | HTTP status, per-domain failure counter                | Exponential backoff; 3 consecutive 403s auto-pauses the domain and raises it in the UI. Never retry through a block. |
| Selector silently breaks after a redesign   | Per-field validation on every observation              | Page routed to `unknown_pages`; domain marked `broken` once failures exceed 20% of a run                             |
| Infinite URL space (faceted nav, calendars) | Run-level URL cap, depth cap                           | Run halts for that domain, reports the pattern that exploded; you add a `deny_pattern` and re-approve                |
| Worker crashes mid-page                     | `locked_until` expiry on the queue row                 | Row returns to `pending` after 120 s; `attempts` increments; 3 attempts moves it to `failed`                         |
| Postgres unavailable                        | Health check, connection errors                        | Workers exit cleanly; run resumes from the queue on restart. No state lives only in memory                           |
| llama-server down                           | Connection refused on proposal                         | Onboarding blocks with a clear message; **crawling is unaffected**, since the model is not in the crawl path         |
| Disk fills (assets or HTML)                 | Pre-run free-space check                               | Run refuses to start below a threshold; HTML purge sweep runs first                                                  |
| Duplicate crawls on restart                 | `UNIQUE (run_id, url_hash)` plus transactional dequeue | Structurally prevented, not retried away                                                                             |
| Browser memory growth                       | Recycling in the render sidecar                        | Browser restarted on a page threshold; contexts capped at 3. A crash there cannot take the worker down (ADR-0016)    |
| Bad LLM proposal                            | Deterministic verification against the real DOM        | Discarded before review; never reaches stored data                                                                   |

### The two that actually matter

**Getting blocked** is handled by the politeness gate plus aggressive auto-pausing. The design choice worth restating: on a 403, the system stops rather than retries. A retry loop against a site that has decided to block you is how a temporary block becomes a permanent one.

**Silent extraction failure** is handled by validation rules and the review inbox. This is the failure that produces no error and corrupts the dataset quietly — the reason validation is mandatory per field rather than optional.
