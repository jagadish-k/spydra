# 001 — Domain model and database schema

**Phase 1** · depends on nothing · everything depends on this

**This is the authoritative schema.** All tables here live in the `crawl`
schema, owned by `api` and `worker`. The BFF has `SELECT` and no write access
(spec 010 §3); the `ui` schema is the BFF's and is specified in
[spec 011](011-bff.md).

`ARCHITECTURE.md` explains _why_ these shapes were chosen. This spec is what
the migration implements.

---

## 1. Schema

```sql
-- Domain registry: lifecycle, politeness config, rendering mode
CREATE TYPE domain_state AS ENUM
  ('discovered','awaiting_approval','active','paused','broken','archived');

CREATE TABLE domains (
  id              BIGSERIAL PRIMARY KEY,
  host            TEXT NOT NULL UNIQUE,
  state           domain_state NOT NULL DEFAULT 'discovered',
  render_mode     TEXT NOT NULL DEFAULT 'static',   -- static | rendered | auto
  crawl_delay_ms  INT  NOT NULL DEFAULT 2000,
  max_concurrency INT  NOT NULL DEFAULT 1,
  in_flight       INT  NOT NULL DEFAULT 0,   -- see the note below
  asset_concurrency INT NOT NULL DEFAULT 5,
  max_depth       INT  NOT NULL DEFAULT 5,
  deny_patterns   TEXT[] NOT NULL DEFAULT '{}',
  respect_robots  BOOLEAN NOT NULL DEFAULT TRUE,
  user_agent      TEXT,
  next_eligible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consecutive_failures INT NOT NULL DEFAULT 0,
  -- ADR-0004 pauses on three CONSECUTIVE 403s; the shared counter above also
  -- counts 429/503, so the refusals need their own (BUILD_PLAN 1.9).
  consecutive_403s INT NOT NULL DEFAULT 0 CHECK (consecutive_403s >= 0),
  -- What the operator configured. The x2 backoff overwrites crawl_delay_ms,
  -- and spec 002 §4's decay stops here, never below (BUILD_PLAN 1.13).
  configured_crawl_delay_ms INT NOT NULL DEFAULT 2000
    CHECK (configured_crawl_delay_ms >= 0),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- ADR-0026: the counter gates claiming, so a negative one is impolite
  -- rather than merely wrong. Completion and the lease sweep both
  -- decrement; this is the backstop against them racing.
  CONSTRAINT in_flight_non_negative CHECK (in_flight >= 0)
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
  -- ADR-0006: hedged, never populated until a platform family appears.
  parent_template_id BIGINT REFERENCES templates(id),
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

-- A crawl run. Referenced by page_observations and crawl_queue.
CREATE TYPE run_state AS ENUM ('running','paused','completed','stopped','failed');

CREATE TABLE runs (
  id            BIGSERIAL PRIMARY KEY,
  state         run_state NOT NULL DEFAULT 'running',
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  domain_ids    BIGINT[] NOT NULL,     -- the selection this run covers
  trigger       TEXT NOT NULL DEFAULT 'manual',
  stats         JSONB NOT NULL DEFAULT '{}',  -- rolled up at completion
  stop_reason   TEXT
);
CREATE INDEX ON runs (started_at DESC);

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
                                -- | 'static_fallback' (spec 012 §4): an AUTO
                                -- domain that wanted a rendered fetch and
                                -- could not have one. TEXT, so adding a value
                                -- needs no migration.
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

-- Current state is a view, not a table. `unchanged` rows are skipped: they
-- are spec 003 §4's lightweight rows (NULL fields by design) and assert
-- "same as the row before", so the newest full row IS the current content.
-- When the page was last seen is pages.last_crawled_at.
CREATE VIEW page_current AS
SELECT DISTINCT ON (page_id) *
FROM page_observations WHERE NOT unchanged
ORDER BY page_id, observed_at DESC;

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
  -- The authoritative list. A closed vocabulary, like domain_state:
  --   'no_template'        no template matches this URL pattern
  --   'empty_extraction'   200, nothing substantive (ADR-0037). A redesign
  --                        OR a soft 404;
  --                        only pages with a prior non-empty observation
  --                        count toward the broken threshold (ADR-0030)
  --   'fetch_error'        non-2xx or timeout
  --   'llm_low_confidence' proposal below threshold (phase 4)
  -- 'validation_failed' was removed: nothing is required, so a field
  -- failing its rule is recorded and routes nothing (ADR-0027).
  reason       TEXT NOT NULL,
  llm_proposal JSONB,           -- selectors the model suggested
  sample_html_path TEXT,
  resolved_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One OPEN row per URL. A page that stays empty run after run is one thing
-- to review, not one per run (ADR-0030 keeps such a domain crawling); once
-- resolved, the same URL failing again opens a new row. Writers insert with
-- ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX uq_unknown_pages_open
  ON unknown_pages (domain_id, url) WHERE resolved_at IS NULL;

-- Bounded per-run event log. Exists so an SSE client that reconnects with
-- Last-Event-ID can be backfilled rather than shown a gap (ADR-0012).
CREATE TABLE run_events (
  id        BIGSERIAL PRIMARY KEY,
  run_id    BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq       BIGINT NOT NULL,          -- monotonic per run; the SSE event id
  kind      TEXT NOT NULL,            -- 'progress'|'page'|'domain_state'|'asset'|'run_state'
  payload   JSONB NOT NULL,
  at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, seq)
);
CREATE INDEX ON run_events (run_id, seq);

-- Asset work queue. Assets are enqueued by page workers and drained by the
-- asset pool; a page worker never blocks on an image (ADR-0003).
CREATE TABLE asset_queue (
  id            BIGSERIAL PRIMARY KEY,
  run_id        BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  observation_id BIGINT NOT NULL REFERENCES page_observations(id) ON DELETE CASCADE,
  source_url    TEXT NOT NULL,
  source_host   TEXT NOT NULL,
  position      INT NOT NULL DEFAULT 0,
  state         TEXT NOT NULL DEFAULT 'pending',  -- pending|in_flight|done|failed
  attempts      INT NOT NULL DEFAULT 0,
  locked_until  TIMESTAMPTZ,
  enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (observation_id, source_url)
);
CREATE INDEX ON asset_queue (state, source_host) WHERE state = 'pending';

-- Sample URLs backing the review screen's pass/fail matrix.
CREATE TABLE template_samples (
  id          BIGSERIAL PRIMARY KEY,
  template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  url         TEXT NOT NULL,
  html_path   TEXT,                  -- cached sample, for offline re-testing
  last_result JSONB NOT NULL DEFAULT '{}',   -- { field: 'pass'|'fail'|'partial' }
  UNIQUE (template_id, url)
);
```

### Why these shapes

- **`templates` keyed on `(domain_id, url_pattern)`** — a domain needs different rules for listing and product pages, and often per category section. Keying on domain alone is a painful migration later.
- **Partial unique index on `is_active`** — guarantees exactly one live template per pattern while keeping every prior version readable.
- **`content_hash` on observations** — a re-crawl that finds nothing changed writes no row beyond a timestamp bump, keeping history meaningful rather than noisy.
- **`validation` JSONB per observation** — records which fields passed their rules at crawl time, so a silently broken selector surfaces in a report rather than as quiet bad data.

**`domains.in_flight` is a cache, not a fact.** It is incremented in the
claim transaction, decremented on completion, and reconciled by the
lease-expiry sweep. Never trust it without reconciliation — a worker killed
mid-fetch leaves it high until the sweep runs.

Asset _host_ backoff state (next-eligible time per CDN host) is deliberately
**not** a table. It lives in process, per ADR-0003: a loose limit is a
throughput knob, not a correctness property. It resets on restart, which is
acceptable.

`max_depth` and `deny_patterns` are per domain because spec 004 reads them
there and the Domain detail screen edits them.

---

## 2. Domain lifecycle

Explicit state on `domains.state`. A domain that is not `active` sends no
requests, which is what makes "block until I approve" cheap.

```
discovered ──propose──> awaiting_approval ──approve──> active
     ▲                         │                        │  │
     │                         └──reject────────────────┘  │
     │                                                     │
  (re-propose)  broken <──validation failures >20%──────────┤
     │             │                                       │
     │             └──re-review──> awaiting_approval        │
     │                                                      │
     └──────── paused <──3× 403, or operator ───────────────┘
                   │
                   └──resume──> active

  any ──archive──> archived   (terminal; data retained)
```

| State               | Crawls? | Entered by                            | Left by                 |
| ------------------- | ------- | ------------------------------------- | ----------------------- |
| `discovered`        | no      | seeding a new host                    | requesting a proposal   |
| `awaiting_approval` | no      | a verified proposal exists            | operator approve/reject |
| `active`            | **yes** | approval                              | pause, break, archive   |
| `broken`            | no      | >20% of a run's pages fail validation | re-review               |
| `paused`            | no      | 3 consecutive 403s, or operator       | operator resume         |
| `archived`          | no      | operator                              | terminal                |

Transitions are a pure function in `domain/lifecycle.py`. Invalid transitions
raise; they are not silently ignored.

---

## 3. Core entities

Domain objects live in `backend/spydra/domain/`, are frozen dataclasses, and
contain **no I/O**. Repositories translate rows to these and back.

```python
@dataclass(frozen=True, slots=True)
class Domain:
    id: DomainId
    host: str
    state: DomainState
    render_mode: RenderMode          # STATIC | RENDERED | AUTO
    crawl_delay_ms: int
    max_concurrency: int
    asset_concurrency: int
    respect_robots: bool
    next_eligible_at: datetime
    consecutive_failures: int

@dataclass(frozen=True, slots=True)
class Template:
    id: TemplateId
    domain_id: DomainId
    url_pattern: re.Pattern[str]
    page_kind: PageKind              # LISTING | PRODUCT
    version: int
    is_active: bool
    discovery: DiscoveryRules
    extraction: Mapping[str, FieldRule]
    proposed_by: ProposedBy          # HUMAN | LLM

@dataclass(frozen=True, slots=True)
class FieldRule:
    selector: str
    attr: str = "text"               # 'text' | an attribute name
    many: bool = False
    required: bool = False
    transform: tuple[Transform, ...] = ()
    validation: tuple[Rule, ...] = ()
    fallback: str | None = None

@dataclass(frozen=True, slots=True)
class Observation:
    page_id: PageId
    run_id: RunId
    template_id: TemplateId | None
    observed_at: datetime
    http_status: int
    strategy: Strategy               # STRUCTURED | SELECTOR | LLM | STATIC_FALLBACK
    content_hash: bytes
    fields: ExtractedFields
    validation: Mapping[str, ValidationResult]
```

`render_mode` has three values. `AUTO` fetches statically and, if the
extraction yields **nothing usable** on a 200 response, retries once through
the browser and records which path succeeded. After a few runs the flag can
be pinned from observed behaviour rather than guessed at onboarding — so the
cost of a wrong guess is one wasted cheap fetch, not a silently empty
extraction.

> **The fallback condition was "the template's required fields fail to
> resolve" and is amended by [ADR-0027](../adr/0027-no-required-fields.md).**
> No field is required any more, so that condition could never be true and
> `AUTO` would have silently become `STATIC` — on a target list where every
> domain needs rendering. It is now the same `empty_extraction` predicate
> that spec 003 §3 uses, so the fallback and the redesign detector cannot
> disagree.

`FieldRule.required` below is **inert** for the same reason: it stays in the
type and in the `templates.extraction` JSONB so prior template versions
(ADR-0006) keep their shape, the loader rejects any attempt to set it, and
nothing reads it.

---

## 4. Authoring tables (phase 4)

Two tables support template authoring. **[Spec 013](013-template-authoring.md)
is authoritative for their contents**; they are listed here so this spec
remains the complete picture of the `crawl` schema.

| Table                    | Purpose                                                                 | Lifetime                    |
| ------------------------ | ----------------------------------------------------------------------- | --------------------------- |
| `crawl.template_drafts`  | working state for a template being authored by form, chat or playground | until approved or discarded |
| `crawl.field_vocabulary` | canonical field names, aliases, types and targets                       | permanent, seeded           |

Two constraints belong here rather than in 013:

- **A draft is not a template.** Nothing in the crawl path may read
  `template_drafts`; only `templates` rows with `is_active = true` are
  crawled from. Enforce by review, and assert it in the scheduler tests.
- **`field_vocabulary.column_name` must name a real column** on
  `product_observations` when `target = 'column'`. A seed test asserts this;
  a typo here silently routes a core field into JSONB, where no cross-domain
  report can see it.

`template_drafts` is the one table in the schema that is allowed to be
deleted outright. Drafts older than 30 days in state `discarded` are purged
by the same job that purges parsed HTML.

---

## 5. Migrations

Alembic, one migration per schema change, in `backend/migrations/`.

- Every migration has a working `downgrade()`. `make migrate-down` is part of
  the test suite; an irreversible migration fails CI.
- Enum changes use `ALTER TYPE … ADD VALUE` where possible; where not, create
  the new type, migrate the column, drop the old.
- Data migrations are separate from schema migrations and idempotent.
- The first migration creates section 1 in one unit. There is no production
  data to preserve, so there is no reason to split it.

---

## 6. Acceptance

- [ ] `make migrate` creates the full schema from empty; `make migrate-down`
      returns to empty. **On a database with nothing in it** — a migration
      that only works against a half-built schema is not a migration.
- [ ] Inserting two `templates` rows with `is_active = true` for the same
      `(domain_id, url_pattern)` is rejected by the partial unique index.
- [ ] `page_current` returns exactly one row per page: the newest that is not
      `unchanged`.
- [ ] Every `domain_state` value in `DESIGN_SYSTEM.md` exists in the enum.
- [ ] Lifecycle transition tests cover every valid edge and reject at least
      three invalid ones.
- [ ] Domain objects import nothing from `adapters/` (enforced by an
      import-linter rule in `make lint`).
- [ ] Every `field_vocabulary` row with `target = 'column'` names an existing
      column on `product_observations`.
- [ ] No crawl-path query references `template_drafts`.
