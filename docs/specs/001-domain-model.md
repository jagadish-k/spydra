# 001 — Domain model and database schema

**Phase 1** · depends on nothing · everything depends on this

> **All tables in this spec live in the `crawl` schema**, owned by `api` and
> `worker`. The BFF has `SELECT` and no write access (spec 010 §3). The
> `ui` schema is the BFF's and is specified in [spec 011](011-bff.md).

`docs/DATA_MODEL.md` holds the core schema and the reasoning behind its
shapes. **That file is incomplete** — it references tables it does not define.
This spec closes those gaps and is the authoritative schema for
implementation.

---

## 1. Gaps in DATA_MODEL.md to close

`DATA_MODEL.md` references `runs(id)` in two foreign keys but never defines
the table. The concurrency model in `ARCHITECTURE.md` requires an asset queue
that does not exist. ADR-0012 requires a retained event log. ADR-0006
specifies a column that is absent.

Add these in the first migration alongside the documented tables:

```sql
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

-- ADR-0006: hedged, never populated until a platform family appears.
ALTER TABLE templates ADD COLUMN parent_template_id BIGINT
  REFERENCES templates(id);
```

### Corrections to the documented schema

`DATA_MODEL.md` and `ARCHITECTURE.md` disagree with themselves in four
places. These are the resolutions; apply them in the first migration.

| Problem | Resolution |
| --- | --- |
| `domain_state` omits **`archived`**, which appears in `ARCHITECTURE.md` §lifecycle, `DESIGN_SYSTEM.md`, the Figma State pill and every mockup | Add `archived` to the enum |
| `render_mode` is commented `'static' \| 'browser'` in the schema but `static \| rendered \| auto` in `ARCHITECTURE.md` §concurrency | **`static \| rendered \| auto` wins.** `browser` is dead terminology from an earlier draft; do not use it anywhere |
| `domains` has no **`in_flight`** column, but the claim query in `ARCHITECTURE.md` and spec 002 §1 requires one to enforce `max_concurrency` | Add `in_flight INT NOT NULL DEFAULT 0` |
| `domains` has no **`asset_concurrency`**, but the Domain detail screen exposes it and the asset gate reads it | Add `asset_concurrency INT NOT NULL DEFAULT 5` |

```sql
ALTER TYPE domain_state ADD VALUE 'archived';

ALTER TABLE domains
  ADD COLUMN in_flight         INT NOT NULL DEFAULT 0,
  ADD COLUMN asset_concurrency INT NOT NULL DEFAULT 5,
  ADD COLUMN max_depth         INT NOT NULL DEFAULT 5,
  ADD COLUMN deny_patterns     TEXT[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN domains.render_mode IS 'static | rendered | auto';
COMMENT ON COLUMN domains.in_flight IS
  'Pages currently being fetched. Incremented in the claim transaction, '
  'decremented on completion, reconciled by the lease-expiry sweep. '
  'Never trust it without reconciliation.';
```

`max_depth` and `deny_patterns` are also added here: spec 004 reads them per
domain, and the Domain detail screen edits them.

Asset *host* backoff state (next-eligible time per CDN host) is deliberately
**not** a table. It lives in process, per ADR-0003: a loose limit is a
throughput knob, not a correctness property. It resets on restart, which is
acceptable.

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

| State | Crawls? | Entered by | Left by |
| --- | --- | --- | --- |
| `discovered` | no | seeding a new host | requesting a proposal |
| `awaiting_approval` | no | a verified proposal exists | operator approve/reject |
| `active` | **yes** | approval | pause, break, archive |
| `broken` | no | >20% of a run's pages fail validation | re-review |
| `paused` | no | 3 consecutive 403s, or operator | operator resume |
| `archived` | no | operator | terminal |

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
    strategy: Strategy               # STRUCTURED | SELECTOR | LLM
    content_hash: bytes
    fields: ExtractedFields
    validation: Mapping[str, ValidationResult]
```

`render_mode` has three values. `AUTO` fetches statically and, if the
template's required fields fail to resolve on a 200 response, retries once
through the browser and records which path succeeded. After a few runs the
flag can be pinned from observed behaviour rather than guessed at onboarding
— so the cost of a wrong guess is one wasted cheap fetch, not a silently
empty extraction.

---

## 3a. Authoring tables (phase 4)

Two tables support template authoring. **[Spec 013](013-template-authoring.md)
is authoritative for their contents**; they are listed here so this spec
remains the complete picture of the `crawl` schema.

| Table | Purpose | Lifetime |
| --- | --- | --- |
| `crawl.template_drafts` | working state for a template being authored by form, chat or playground | until approved or discarded |
| `crawl.field_vocabulary` | canonical field names, aliases, types and targets | permanent, seeded |

Two constraints belong to this spec rather than 013:

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

## 4. Migrations

Alembic, one migration per schema change, in `backend/migrations/`.

- Every migration has a working `downgrade()`. `make migrate-down` is part of
  the test suite; an irreversible migration fails CI.
- Enum changes use `ALTER TYPE … ADD VALUE` where possible; where not, create
  the new type, migrate the column, drop the old.
- Data migrations are separate from schema migrations and idempotent.
- The first migration creates everything in `DATA_MODEL.md` plus section 1
  above, as one unit. There is no production data to preserve.

---

## 5. Acceptance

- [ ] `make migrate` creates the full schema from empty; `make migrate-down`
      returns to empty.
- [ ] Inserting two `templates` rows with `is_active = true` for the same
      `(domain_id, url_pattern)` is rejected by the partial unique index.
- [ ] `page_current` returns exactly one row per page, the newest.
- [ ] Every `domain_state` value in `DESIGN_SYSTEM.md` exists in the enum.
- [ ] Lifecycle transition tests cover every valid edge and reject at least
      three invalid ones.
- [ ] Domain objects import nothing from `adapters/` (enforced by an
      import-linter rule in `make lint`).
- [ ] Every `field_vocabulary` row with `target = 'column'` names an existing
      column on `product_observations`.
- [ ] No crawl-path query references `template_drafts`.
