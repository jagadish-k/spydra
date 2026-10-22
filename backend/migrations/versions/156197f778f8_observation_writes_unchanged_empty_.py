"""observation writes: unchanged, empty_extraction, extraction_rung

BUILD_PLAN 1.11. Three columns on `page_observations`, and a rebuilt
`page_current`.

- `unchanged` — spec 003 §4's lightweight row. The `Observation` entity has
  carried this flag since 1.2 and had no column to write it to; spec 001 §1's
  DDL does not list one either.
- `empty_extraction` — ADR-0027's verdict, computed in Python and persisted.
  The `broken` threshold (ADR-0030) is a join over this column. Recomputing
  emptiness in SQL would be a fourth definition of a predicate ADR-0027
  requires to have exactly one, and the most able to disagree:
  `attributes = '{}'::jsonb` is not the question `all(is_empty(v))` asks.
- `extraction_rung` — which rung produced the fields, for the rows where
  `strategy` is spending itself on spec 012 §4's `static_fallback` (see
  `.tasks/feat-1.11-observation-writes.md` open question 1).

**`page_current` is recreated, and that is not housekeeping.** ADR-0007 makes
the view the only way anything reads current state, and Postgres expands
`SELECT *` at CREATE time: measured on this database before the fix, the view
carried the 20 pre-existing columns and none of the three added above. Every
reader of `page_current` — the review inbox, phase 5's extraction-health and
broken-template reports — would have queried a view that silently lacked the
regression flag the report is about. `tests/adapters/postgres/test_schema.py`
now holds the two column lists equal so the next column-adding migration
cannot forget this.

Revision ID: 156197f778f8
Revises: 2071b5ff83e1
Create Date: 2026-10-21 16:27:49.666638

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from spydra.adapters.postgres.tables import PAGE_CURRENT_NAME, PAGE_CURRENT_SQL

# revision identifiers, used by Alembic.
revision: str = "156197f778f8"
down_revision: str | None = "2071b5ff83e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "page_observations",
        sa.Column("extraction_rung", sa.Text(), nullable=True),
        schema="crawl",
    )
    op.add_column(
        "page_observations",
        sa.Column("unchanged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="crawl",
    )
    op.add_column(
        "page_observations",
        sa.Column(
            "empty_extraction",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="crawl",
    )
    _rebuild_page_current()


def downgrade() -> None:
    # The view first: it depends on the columns, so dropping them while it
    # still selects `*` over them fails with a dependency error. Proven by
    # running `downgrade -1` against a populated database, not reasoned.
    op.execute(f"DROP VIEW IF EXISTS {PAGE_CURRENT_NAME}")
    op.drop_column("page_observations", "empty_extraction", schema="crawl")
    op.drop_column("page_observations", "unchanged", schema="crawl")
    op.drop_column("page_observations", "extraction_rung", schema="crawl")
    op.execute(PAGE_CURRENT_SQL)


def _rebuild_page_current() -> None:
    """Re-expand `SELECT *` over the widened table (ADR-0007).

    The definition is imported from `tables.py` rather than copied: two
    copies of the view's SQL is how a later migration recreates yesterday's
    view, and `migrations/env.py` already treats that constant as the one
    definition (its `include_object` filter keeps autogenerate from proposing
    to drop a view it cannot see).
    """
    op.execute(f"DROP VIEW IF EXISTS {PAGE_CURRENT_NAME}")
    op.execute(PAGE_CURRENT_SQL)
