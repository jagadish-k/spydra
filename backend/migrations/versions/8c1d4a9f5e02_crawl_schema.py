"""crawl schema: the whole of spec 001 §1 in one unit

BUILD_PLAN 1.1. Spec 001 §5 is explicit that the first migration creates
section 1 as one migration: there is no production data to preserve, so
splitting it buys nothing and costs a dozen revisions nobody will ever step
through individually.

**Why this file repeats what `spydra/adapters/postgres/tables.py` says.**
tables.py describes the schema as it is *now* and is what `make revision`
autogenerates against. A migration describes a *transition*, then, and has to
keep describing that same transition after tables.py has moved on — a
migration that called `metadata.create_all()` would silently produce a
different schema every time the metadata changed, and `alembic downgrade
base` would stop matching the upgrade that ran. The duplication is the point;
it is a frozen snapshot, not a second source of truth. The ops below were
rendered mechanically from tables.py rather than transcribed.

Two things are NOT auto-generated and are handled explicitly:

1. **The enum types.** `op.create_table` emits CREATE TYPE on first use, but
   `op.drop_table` does not drop it. An un-dropped type makes the second
   `upgrade head` after a `downgrade base` fail with "type already exists",
   which is exactly the cycle `make migrate-down` and CI run (TESTING.md §2).
2. **`page_current`.** A view, not a table (ADR-0007), so it has no place in
   the metadata. It is dropped first on downgrade: it depends on
   `page_observations`.

Nothing here emits CREATE SCHEMA. `crawl` is created by
docker/init-schemas.sql before any migration runs, and the api role holds
CREATE on the schema rather than on the database — see migrations/env.py.

Revision ID: 8c1d4a9f5e02
Revises: 2ff8b22bee8f
Create Date: 2026-10-17 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from spydra.adapters.postgres.tables import PAGE_CURRENT_NAME, PAGE_CURRENT_SQL, SCHEMA

# revision identifiers, used by Alembic.
revision: str = "8c1d4a9f5e02"
down_revision: str | None = "2ff8b22bee8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Created by the first op.create_table that uses each, dropped explicitly in
# downgrade(). Listed once so the two halves cannot disagree.
_ENUMS = ("domain_state", "run_state")


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
        schema="crawl",
    )
    op.create_table(
        "domains",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "discovered",
                "awaiting_approval",
                "active",
                "paused",
                "broken",
                "archived",
                name="domain_state",
                schema="crawl",
            ),
            server_default="discovered",
            nullable=False,
        ),
        sa.Column("render_mode", sa.Text(), server_default="static", nullable=False),
        sa.Column("crawl_delay_ms", sa.Integer(), server_default=sa.text("2000"), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("in_flight", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("asset_concurrency", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("max_depth", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "deny_patterns",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("respect_robots", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "next_eligible_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host"),
        schema="crawl",
    )
    op.create_index(
        "ix_domains_next_eligible_active",
        "domains",
        ["next_eligible_at"],
        unique=False,
        schema="crawl",
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "running",
                "paused",
                "completed",
                "stopped",
                "failed",
                name="run_state",
                schema="crawl",
            ),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("domain_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("trigger", sa.Text(), server_default="manual", nullable=False),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="crawl",
    )
    op.create_index(
        "ix_runs_started_at_desc",
        "runs",
        [sa.literal_column("started_at DESC")],
        unique=False,
        schema="crawl",
    )
    op.create_table(
        "crawl_queue",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.LargeBinary(), nullable=False),
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["domain_id"], ["crawl.domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["crawl.runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "url_hash"),
        schema="crawl",
    )
    op.create_index(
        "ix_crawl_queue_domain_pending",
        "crawl_queue",
        ["domain_id", "state"],
        unique=False,
        schema="crawl",
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["crawl.runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq"),
        schema="crawl",
    )
    op.create_index(
        "ix_run_events_run_seq", "run_events", ["run_id", "seq"], unique=False, schema="crawl"
    )
    op.create_table(
        "templates",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url_pattern", sa.Text(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "discovery",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "extraction",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("proposed_by", sa.Text(), server_default="human", nullable=False),
        sa.Column("parent_template_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["domain_id"], ["crawl.domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_template_id"],
            ["crawl.templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_id", "url_pattern", "version"),
        schema="crawl",
    )
    op.create_index(
        "one_active_per_pattern",
        "templates",
        ["domain_id", "url_pattern"],
        unique=True,
        schema="crawl",
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "unknown_pages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("llm_proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sample_html_path", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["domain_id"], ["crawl.domains.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="crawl",
    )
    op.create_table(
        "pages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.LargeBinary(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=True),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["domain_id"], ["crawl.domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["crawl.templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_id", "url_hash"),
        schema="crawl",
    )
    op.create_table(
        "template_samples",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("html_path", sa.Text(), nullable=True),
        sa.Column(
            "last_result",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["template_id"], ["crawl.templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "url"),
        schema="crawl",
    )
    op.create_table(
        "page_observations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=True),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("price_amount", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("price_currency", sa.CHAR(length=3), nullable=True),
        sa.Column("availability", sa.Text(), nullable=True),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("category_path", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "supplier",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "validation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.Column("raw_html_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["crawl.pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["crawl.runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["crawl.templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="crawl",
    )
    op.create_index(
        "ix_page_observations_page_observed",
        "page_observations",
        ["page_id", sa.literal_column("observed_at DESC")],
        unique=False,
        schema="crawl",
    )
    op.create_table(
        "asset_queue",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_host", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["crawl.page_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["crawl.runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", "source_url"),
        schema="crawl",
    )
    op.create_index(
        "ix_asset_queue_pending_host",
        "asset_queue",
        ["state", "source_host"],
        unique=False,
        schema="crawl",
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "observation_assets",
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["crawl.assets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["crawl.page_observations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("observation_id", "asset_id", "source_url"),
        schema="crawl",
    )

    # Current state is a view over the append-only table, never a second
    # table that something could UPDATE (ADR-0007, AGENTS.md rule 13).
    op.execute(PAGE_CURRENT_SQL)


def downgrade() -> None:
    # The view depends on page_observations, so it goes first.
    op.execute(f"DROP VIEW IF EXISTS {PAGE_CURRENT_NAME}")

    op.drop_table("observation_assets", schema=SCHEMA)
    op.drop_table("asset_queue", schema=SCHEMA)
    op.drop_table("page_observations", schema=SCHEMA)
    op.drop_table("template_samples", schema=SCHEMA)
    op.drop_table("pages", schema=SCHEMA)
    op.drop_table("unknown_pages", schema=SCHEMA)
    op.drop_table("templates", schema=SCHEMA)
    op.drop_table("run_events", schema=SCHEMA)
    op.drop_table("crawl_queue", schema=SCHEMA)
    op.drop_table("runs", schema=SCHEMA)
    op.drop_table("domains", schema=SCHEMA)
    op.drop_table("assets", schema=SCHEMA)

    # DROP TABLE leaves the enum types behind. Without this, upgrade -> down
    # -> upgrade fails on "type already exists" — and that cycle is what CI
    # runs (TESTING.md §2 § Migrations).
    for name in _ENUMS:
        postgresql.ENUM(name=name, schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
