# Spydra — data model

> **This file is the core schema but it is not complete, and it contains four
> known errors.** [`specs/001-domain-model.md`](specs/001-domain-model.md) is
> the authoritative schema for implementation: it adds the missing tables
> (`runs`, `run_events`, `asset_queue`, `template_samples`) and corrects
> `domain_state`, `render_mode`, `in_flight` and `asset_concurrency`.
> Read that spec before writing the migration.

> Extracted from the architecture blueprint. `ARCHITECTURE.md` explains why
> these shapes were chosen; the spec above supersedes this file on detail.

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
