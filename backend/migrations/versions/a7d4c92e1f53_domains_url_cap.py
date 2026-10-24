"""domains.url_cap: the per-run per-domain queue ceiling (BUILD_PLAN 2.5)

Spec 004 §3's backstop trap defence, ADR-0040. The column lives on the
domain for the same reason `max_depth` does (2.3): an operator-editable
per-domain crawl shape. The default (20,000) is calibrated to the fixture
site's reachable facet space being just above it — the cap is meant to be
crossed by a trap, not by an honest crawl.

Not surfaced in the YAML loader (it is replaced in 3.2) or the API (a UI
field is 3.x); breach tests set it by SQL.

Revision ID: a7d4c92e1f53
Revises: 02a392d77c4a
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d4c92e1f53"
down_revision: str | None = "02a392d77c4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("url_cap", sa.Integer(), server_default=sa.text("20000"), nullable=False),
        schema="crawl",
    )
    # A cap of zero or less would fail every enqueue, halting every run on
    # its first discovery. Hand-written: autogenerate does not see CHECKs.
    op.create_check_constraint("url_cap_positive", "domains", "url_cap > 0", schema="crawl")


def downgrade() -> None:
    op.drop_constraint("url_cap_positive", "domains", type_="check", schema="crawl")
    op.drop_column("domains", "url_cap", schema="crawl")
