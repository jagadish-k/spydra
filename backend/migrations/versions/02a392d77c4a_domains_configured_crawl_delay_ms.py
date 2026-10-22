"""domains.configured_crawl_delay_ms: the floor spec 002 §4's decay needs

BUILD_PLAN 1.13. Spec 002 §4 decays `crawl_delay_ms` "toward its configured
value by 10% per success, never below it", and the ×2 backoff overwrites
`crawl_delay_ms` itself, so nothing recorded what was configured. The
politeness gate took the floor as a parameter with a 2000 ms default
(BUILD_PLAN 1.9 open question 1), which silently replaced any operator value
after the first 429.

Existing rows get 2000, which is the floor the gate already assumed for every
domain, so the upgrade changes no behaviour. Copying `crawl_delay_ms` instead
would freeze a backed-off delay in place as the floor.

Revision ID: 02a392d77c4a
Revises: b6a0569d82bc
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02a392d77c4a"
down_revision: str | None = "b6a0569d82bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column(
            "configured_crawl_delay_ms",
            sa.Integer(),
            server_default=sa.text("2000"),
            nullable=False,
        ),
        schema="crawl",
    )
    # A negative floor would let the decay drive the delay below zero, which
    # is no delay at all. Written by hand: autogenerate does not see CHECKs
    # (the same reason `5b7c0e1a94d3` exists).
    op.create_check_constraint(
        "configured_crawl_delay_ms_non_negative",
        "domains",
        "configured_crawl_delay_ms >= 0",
        schema="crawl",
    )


def downgrade() -> None:
    op.drop_constraint(
        "configured_crawl_delay_ms_non_negative", "domains", type_="check", schema="crawl"
    )
    op.drop_column("domains", "configured_crawl_delay_ms", schema="crawl")
