"""runs.next_seq: the per-run event counter (BUILD_PLAN 2.8, ADR-0042)

Every `run_events` emission reserves `seq` from this counter — one
`UPDATE crawl.runs SET next_seq = next_seq + 1 .. RETURNING` whose own row
lock serialises reservers, so `seq` is per-run monotonic AND gap-free by
construction (a rollback discards reservation and insert together).

Revision ID: f4b2d6a91c03
Revises: e5f2c9a71b34
Create Date: 2026-10-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4b2d6a91c03"
down_revision: str | None = "e5f2c9a71b34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("next_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        schema="crawl",
    )
    # Correct for any database state, not just today's empty table: the
    # counter must continue from the highest seq the run ever emitted, or
    # the first post-migration emission duplicates a (run_id, seq).
    op.execute(
        "UPDATE crawl.runs"
        " SET next_seq = coalesce((SELECT max(e.seq) FROM crawl.run_events e"
        "                          WHERE e.run_id = runs.id), 0)"
    )


def downgrade() -> None:
    op.drop_column("runs", "next_seq", schema="crawl")
