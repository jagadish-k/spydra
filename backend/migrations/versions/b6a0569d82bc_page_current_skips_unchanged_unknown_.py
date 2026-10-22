"""page_current skips unchanged rows; one open unknown_pages row per URL

Follow-up to BUILD_PLAN 1.11 (`.tasks/fix-1.11-review-findings.md`).

- **`page_current` gains `WHERE NOT unchanged`.** Spec 003 §4's lightweight
  row has NULL fields by design, and `page_current` returned it, so from a
  page's second run every stable page read as empty through the only
  sanctioned reader of current state (ADR-0007). Measured before the fix: a
  stable product crawled twice read `(title NULL, price NULL)`.
- **`uq_unknown_pages_open`**: one OPEN row per `(domain_id, url)`. Without
  it, a page that stays empty reopened the review inbox every run.
- **`ix_page_observations_run_page`**: the broken-template detector reads one
  run's pages, and the only index was per page.

Revision ID: b6a0569d82bc
Revises: 156197f778f8
Create Date: 2026-10-22 05:12:03.621558

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from spydra.adapters.postgres.tables import PAGE_CURRENT_NAME, SCHEMA

# revision identifiers, used by Alembic.
revision: str = "b6a0569d82bc"
down_revision: str | None = "156197f778f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen, both of them: a migration carries the SQL it shipped (see
# `8c1d4a9f5e02`).
_SKIPS_UNCHANGED = f"""
CREATE VIEW {SCHEMA}.page_current AS
SELECT DISTINCT ON (page_id) *
FROM {SCHEMA}.page_observations
WHERE NOT unchanged
ORDER BY page_id, observed_at DESC
"""

_EVERY_ROW = f"""
CREATE VIEW {SCHEMA}.page_current AS
SELECT DISTINCT ON (page_id) *
FROM {SCHEMA}.page_observations
ORDER BY page_id, observed_at DESC
"""

# A database that ran 1.11 already holds duplicate open rows, and the unique
# index cannot be built over them. The older duplicates are RESOLVED, not
# deleted: the newest stays open for the operator, and the history of how
# often the page came back is kept.
_RESOLVE_DUPLICATES = f"""
UPDATE {SCHEMA}.unknown_pages u
SET resolved_at = now()
WHERE u.resolved_at IS NULL
  AND EXISTS (
      SELECT 1 FROM {SCHEMA}.unknown_pages newer
      WHERE newer.domain_id = u.domain_id
        AND newer.url = u.url
        AND newer.resolved_at IS NULL
        AND newer.id > u.id
  )
"""


def upgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {PAGE_CURRENT_NAME}")
    op.execute(_SKIPS_UNCHANGED)
    op.create_index(
        "ix_page_observations_run_page",
        "page_observations",
        ["run_id", "page_id"],
        unique=False,
        schema="crawl",
    )
    op.execute(_RESOLVE_DUPLICATES)
    op.create_index(
        "uq_unknown_pages_open",
        "unknown_pages",
        ["domain_id", "url"],
        unique=True,
        schema="crawl",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    # The duplicates resolved on the way up stay resolved: which of them were
    # open before is not recorded, and reopening every resolved row would
    # undo the operator's own resolutions too.
    op.drop_index(
        "uq_unknown_pages_open",
        table_name="unknown_pages",
        schema="crawl",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_index("ix_page_observations_run_page", table_name="page_observations", schema="crawl")
    op.execute(f"DROP VIEW IF EXISTS {PAGE_CURRENT_NAME}")
    op.execute(_EVERY_ROW)
