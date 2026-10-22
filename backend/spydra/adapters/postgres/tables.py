"""The `crawl` schema as SQLAlchemy Core metadata (ADR-0014).

**This is the single description of the schema.** The migration in
`migrations/versions/` is written from it and `migrations/env.py` points
`target_metadata` here, so `make revision` autogenerates against something
real instead of emitting empty revisions.

It is Core `Table` objects and not ORM models on purpose: spec 001 §3 makes
the domain entities frozen dataclasses with no I/O, and repositories
translate rows to them by hand. Nothing here is mapped to a class, so there
is no second place a column can be renamed.

`docs/specs/001-domain-model.md` §1 is authoritative. Where this file and
that spec disagree, the spec is right until proven otherwise.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

SCHEMA = "crawl"

# Every table lives in `crawl`; the schema itself is created by
# docker/init-schemas.sql, never by a migration (migrations/env.py explains
# why — the api role holds CREATE on the schema, not on the database).
metadata = sa.MetaData(schema=SCHEMA)

_NOW = sa.text("now()")
# Spelled as SQL text, not sa.true()/sa.false(). Those compile correctly here
# but alembic's migration RENDERER turns them into sa.text("1")/sa.text("0"),
# and `DEFAULT 0` on a boolean column is a hard error in Postgres. Rendering
# is how this file reaches a migration, so the trap is removed at the source.
_TRUE = sa.text("true")
_FALSE = sa.text("false")
_EMPTY_JSONB = sa.text("'{}'::jsonb")
_EMPTY_ARRAY = sa.text("'{}'")

# --- enums ------------------------------------------------------------------
# Attached to the metadata so autogenerate sees them. The migration creates
# and drops them explicitly, because DROP TABLE does not drop a type.

domain_state = sa.Enum(
    "discovered",
    "awaiting_approval",
    "active",
    "paused",
    "broken",
    "archived",
    name="domain_state",
    schema=SCHEMA,
    metadata=metadata,
)

run_state = sa.Enum(
    "running",
    "paused",
    "completed",
    "stopped",
    "failed",
    name="run_state",
    schema=SCHEMA,
    metadata=metadata,
)

# --- domains ----------------------------------------------------------------

domains = sa.Table(
    "domains",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("host", sa.Text, nullable=False, unique=True),
    sa.Column("state", domain_state, nullable=False, server_default="discovered"),
    sa.Column("render_mode", sa.Text, nullable=False, server_default="static"),
    sa.Column("crawl_delay_ms", sa.Integer, nullable=False, server_default=sa.text("2000")),
    sa.Column("max_concurrency", sa.Integer, nullable=False, server_default=sa.text("1")),
    # A cache, not a fact (spec 001 §1): incremented in the claim
    # transaction, decremented on completion, reconciled by the lease sweep.
    # Never trusted without reconciliation.
    sa.Column("in_flight", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("asset_concurrency", sa.Integer, nullable=False, server_default=sa.text("5")),
    sa.Column("max_depth", sa.Integer, nullable=False, server_default=sa.text("5")),
    sa.Column("deny_patterns", pg.ARRAY(sa.Text), nullable=False, server_default=_EMPTY_ARRAY),
    sa.Column("respect_robots", sa.Boolean, nullable=False, server_default=_TRUE),
    sa.Column("user_agent", sa.Text),
    sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default=sa.text("0")),
    # Separate from `consecutive_failures` on purpose. Spec 002 §4 increments
    # that one for 403, 429 and 503 alike, while ADR-0004 pauses on three
    # consecutive **403s** — one counter cannot answer both questions, and
    # reading the pause off the shared one pauses a domain that refused us
    # once and was busy twice (BUILD_PLAN 1.9).
    sa.Column("consecutive_403s", sa.Integer, nullable=False, server_default=sa.text("0")),
    # What the operator set, which `crawl_delay_ms` cannot remember: the ×2
    # backoff (spec 002 §4) overwrites that column, and the 10% decay has to
    # stop somewhere ("never below it"). Without this the floor was a
    # constant in the gate and an operator's 5 s was gone after one 429
    # (BUILD_PLAN 1.9 open question 1, closed in 1.13).
    sa.Column(
        "configured_crawl_delay_ms",
        sa.Integer,
        nullable=False,
        server_default=sa.text("2000"),
    ),
    sa.Column("notes", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    # ADR-0026: the counter gates claiming, so a NEGATIVE one lets two workers
    # past the gate and fetch one host concurrently — real rudeness, arrived
    # at through the mechanism meant to prevent it. Completion (spec 002 §2)
    # and the lease sweep (§3) both decrement, so a race between them can
    # double-decrement. This is a backstop, not the gate: it makes that bug
    # loud rather than silent.
    sa.CheckConstraint("in_flight >= 0", name="in_flight_non_negative"),
    sa.CheckConstraint("consecutive_403s >= 0", name="consecutive_403s_non_negative"),
    # The claim query's driving index (spec 002 §1). Partial, because only
    # active domains are ever eligible.
    sa.Index(
        "ix_domains_next_eligible_active",
        "next_eligible_at",
        postgresql_where=sa.text("state = 'active'"),
    ),
)

# --- templates --------------------------------------------------------------

templates = sa.Table(
    "templates",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "domain_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.domains.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("url_pattern", sa.Text, nullable=False),  # regex over path+query
    sa.Column("page_kind", sa.Text, nullable=False),  # 'listing' | 'product'
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=_FALSE),
    sa.Column("discovery", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("extraction", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("proposed_by", sa.Text, nullable=False, server_default="human"),
    # ADR-0006: hedged, never populated until a platform family appears.
    sa.Column("parent_template_id", sa.BigInteger, sa.ForeignKey(f"{SCHEMA}.templates.id")),
    sa.Column("approved_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.UniqueConstraint("domain_id", "url_pattern", "version"),
    # Exactly one live template per pattern, every prior version still
    # readable (ADR-0006, spec 001 § Why these shapes).
    sa.Index(
        "one_active_per_pattern",
        "domain_id",
        "url_pattern",
        unique=True,
        postgresql_where=sa.text("is_active"),
    ),
)

# --- pages ------------------------------------------------------------------

pages = sa.Table(
    "pages",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "domain_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.domains.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("url", sa.Text, nullable=False),  # canonicalised
    sa.Column("url_hash", sa.LargeBinary, nullable=False),  # sha256
    sa.Column("page_kind", sa.Text),
    sa.Column("template_id", sa.BigInteger, sa.ForeignKey(f"{SCHEMA}.templates.id")),
    sa.Column("depth", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("last_crawled_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("domain_id", "url_hash"),
)

# --- runs -------------------------------------------------------------------

runs = sa.Table(
    "runs",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("state", run_state, nullable=False, server_default="running"),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("domain_ids", pg.ARRAY(sa.BigInteger), nullable=False),
    sa.Column("trigger", sa.Text, nullable=False, server_default="manual"),
    sa.Column("stats", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("stop_reason", sa.Text),
    sa.Index("ix_runs_started_at_desc", sa.text("started_at DESC")),
)

# --- observations -----------------------------------------------------------

page_observations = sa.Table(
    "page_observations",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "page_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.pages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("run_id", sa.BigInteger, sa.ForeignKey(f"{SCHEMA}.runs.id"), nullable=False),
    sa.Column("template_id", sa.BigInteger, sa.ForeignKey(f"{SCHEMA}.templates.id")),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("http_status", sa.Integer),
    # Over the NORMALISED extracted fields, never the raw markup (ADR-0007,
    # spec 003 §4). Hashing the HTML marks every page changed every run.
    sa.Column("content_hash", sa.LargeBinary),
    sa.Column("strategy", sa.Text),
    # Which extraction rung produced the fields. `strategy` cannot say when
    # it is carrying spec 012 §4's `static_fallback`, which is a statement
    # about the FETCH; without this a render-down run reports zero selector
    # and zero structured extractions (`1.7` open question 2).
    sa.Column("extraction_rung", sa.Text),
    # Spec 003 §4's lightweight row: the page's hash matched its predecessor,
    # so the fields are not repeated. The `Observation` entity has carried
    # this flag since `1.2` and had nowhere to write it.
    sa.Column("unchanged", sa.Boolean, nullable=False, server_default=sa.text("false")),
    # ADR-0027's verdict, computed in Python and persisted. The `broken`
    # threshold is a JOIN over this column; recomputing emptiness in SQL
    # would be a fourth definition of the predicate ADR-0027 requires to
    # have exactly one (`attributes = '{}'::jsonb` is a different question
    # from `all(is_empty(v))`).
    sa.Column("empty_extraction", sa.Boolean, nullable=False, server_default=sa.text("false")),
    # typed core fields
    sa.Column("title", sa.Text),
    sa.Column("price_amount", sa.Numeric(14, 4)),
    sa.Column("price_currency", sa.CHAR(3)),
    sa.Column("availability", sa.Text),
    sa.Column("vendor", sa.Text),
    sa.Column("category_path", pg.ARRAY(sa.Text)),
    sa.Column("description", sa.Text),
    # everything site-specific
    sa.Column("attributes", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("supplier", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("validation", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.Column("raw_html_path", sa.Text),  # gzipped, purged after 7 days
    sa.Column("raw_html_expires_at", sa.DateTime(timezone=True)),
    sa.Index("ix_page_observations_page_observed", "page_id", sa.text("observed_at DESC")),
    # The broken-template detector reads one run's pages after every empty
    # page (ADR-0030). Without this the only index is per page, and every
    # read was a scan of the whole history.
    sa.Index("ix_page_observations_run_page", "run_id", "page_id"),
)

# `page_current` is a VIEW over this table, not a column or a second table
# (ADR-0007). It is created by the migration as raw SQL and is deliberately
# absent from this metadata — see PAGE_CURRENT_SQL below and the
# `include_object` filter in migrations/env.py, which keeps autogenerate from
# proposing to drop a view it cannot see a definition for.
#
# **`unchanged` rows are skipped** (ADR-0033). They are spec 003 §4's lightweight rows,
# with NULL fields by design, and an `unchanged` row asserts "same content as
# the observation before". So the newest row that is NOT `unchanged` *is* the
# current content. Returning the lightweight row made every stable page read
# empty from its second run. When a page was last seen is
# `pages.last_crawled_at`.
#
# This constant is the CURRENT definition. A migration that creates the view
# freezes the SQL it shipped as a literal, because importing this would make
# an old revision create a view over columns that do not exist yet.
PAGE_CURRENT_SQL = f"""
CREATE VIEW {SCHEMA}.page_current AS
SELECT DISTINCT ON (page_id) *
FROM {SCHEMA}.page_observations
WHERE NOT unchanged
ORDER BY page_id, observed_at DESC
"""

PAGE_CURRENT_NAME = f"{SCHEMA}.page_current"

# --- queues -----------------------------------------------------------------

crawl_queue = sa.Table(
    "crawl_queue",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "run_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "domain_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.domains.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("url_hash", sa.LargeBinary, nullable=False),
    sa.Column("depth", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("locked_until", sa.DateTime(timezone=True)),
    sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.UniqueConstraint("run_id", "url_hash"),  # dedupe within a run
    sa.Index(
        "ix_crawl_queue_domain_pending",
        "domain_id",
        "state",
        postgresql_where=sa.text("state = 'pending'"),
    ),
)

asset_queue = sa.Table(
    "asset_queue",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "run_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.page_observations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("source_url", sa.Text, nullable=False),
    sa.Column("source_host", sa.Text, nullable=False),
    sa.Column("position", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("locked_until", sa.DateTime(timezone=True)),
    sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.UniqueConstraint("observation_id", "source_url"),
    sa.Index(
        "ix_asset_queue_pending_host",
        "state",
        "source_host",
        postgresql_where=sa.text("state = 'pending'"),
    ),
)

# --- assets -----------------------------------------------------------------

assets = sa.Table(
    "assets",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    # Deduped by content across every page, which is why the hash and not the
    # URL is unique.
    sa.Column("content_hash", sa.LargeBinary, nullable=False, unique=True),
    sa.Column("path", sa.Text, nullable=False),
    sa.Column("mime", sa.Text),
    sa.Column("width", sa.Integer),
    sa.Column("height", sa.Integer),
    sa.Column("bytes", sa.BigInteger),
    sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
)

observation_assets = sa.Table(
    "observation_assets",
    metadata,
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.page_observations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("asset_id", sa.BigInteger, sa.ForeignKey(f"{SCHEMA}.assets.id"), primary_key=True),
    sa.Column("source_url", sa.Text, nullable=False, primary_key=True),
    sa.Column("position", sa.Integer),
)

# --- review inbox and events ------------------------------------------------

unknown_pages = sa.Table(
    "unknown_pages",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "domain_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.domains.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("llm_proposal", pg.JSONB),
    sa.Column("sample_html_path", sa.Text),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    # One OPEN row per URL. A page that stays empty run after run is one
    # thing for the operator to look at, not one per run; once resolved, the
    # same URL failing again opens a new row (spec 001 §1).
    sa.Index(
        "uq_unknown_pages_open",
        "domain_id",
        "url",
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    ),
)

run_events = sa.Table(
    "run_events",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "run_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Monotonic per run; this is the SSE event id a reconnecting client sends
    # back as Last-Event-ID (ADR-0012).
    sa.Column("seq", sa.BigInteger, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("payload", pg.JSONB, nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.UniqueConstraint("run_id", "seq"),
    sa.Index("ix_run_events_run_seq", "run_id", "seq"),
)

template_samples = sa.Table(
    "template_samples",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "template_id",
        sa.BigInteger,
        sa.ForeignKey(f"{SCHEMA}.templates.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("html_path", sa.Text),  # cached sample, for offline re-testing
    sa.Column("last_result", pg.JSONB, nullable=False, server_default=_EMPTY_JSONB),
    sa.UniqueConstraint("template_id", "url"),
)

# Spec 001 §4's `template_drafts` and `field_vocabulary` are NOT here. They
# are phase-4 tables, spec 013 is authoritative for their contents, and §1 —
# which is what 1.1 implements — does not contain them.
