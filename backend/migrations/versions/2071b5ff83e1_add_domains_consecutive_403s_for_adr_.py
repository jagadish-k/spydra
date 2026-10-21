"""add domains.consecutive_403s for ADR-0004

Revision ID: 2071b5ff83e1
Revises: 5b7c0e1a94d3
Create Date: 2026-10-21 16:03:12.297298

ADR-0004 pauses a domain on three **consecutive 403s**, while spec 002 §4
increments `consecutive_failures` for 403, 429 and 503 alike. One counter
cannot answer both: read off the shared one, a domain that refused us once
and was busy twice gets paused, and the operator has to resume by hand a
domain that never blocked us (BUILD_PLAN 1.9).

**Why a column rather than worker memory.** The politeness gate computed this
count and had nowhere to put it, which review found before `1.13` consumed
it. In-process politeness state is what ADR-0003 and ADR-0026 rejected, and
the failure here is the one ADR-0004 exists to prevent: a domain 403s twice,
the worker restarts or the next claim lands in another replica, the count is
zero again — and it refuses for ever while never reaching three. That would
have passed every unit test.

The `CHECK` is written by hand because Alembic's autogenerate does not detect
check constraints, the same reason `5b7c0e1a94d3` exists for `in_flight`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2071b5ff83e1"
down_revision: str | None = "5b7c0e1a94d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column(
            "consecutive_403s",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="crawl",
    )
    # Same reasoning as `in_flight >= 0` (ADR-0026 §Consequences): a counter
    # that can go negative lets a guard pass more often than it should. Here
    # a negative count would push the pause further away on every decrement,
    # so a domain being refused would take more than three 403s to stop.
    op.create_check_constraint(
        "consecutive_403s_non_negative",
        "domains",
        "consecutive_403s >= 0",
        schema="crawl",
    )


def downgrade() -> None:
    # The constraint goes with the column, but drop it explicitly rather than
    # relying on the cascade: `make migrate-down` runs this in CI and an
    # irreversible migration fails the build (TESTING.md §2).
    op.drop_constraint("consecutive_403s_non_negative", "domains", type_="check", schema="crawl")
    op.drop_column("domains", "consecutive_403s", schema="crawl")
