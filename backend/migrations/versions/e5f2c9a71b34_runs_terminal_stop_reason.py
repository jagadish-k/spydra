"""runs: every non-completed terminal state carries a stop_reason

BUILD_PLAN 2.7, ADR-0041. The invariant — `completed` is the only terminal
state allowed a NULL `stop_reason` — made structural: a CHECK a future
writer cannot violate silently. `paused` is deliberately on the NULL side:
it is not terminal (the enum's terminal set is `completed|stopped|failed`),
it is resumable, and it exists precisely to be resumed. 2.5's cap-breach
rows already write a reason, so there is no data migration.

Hand-written, like 2.5's `url_cap_positive`: autogenerate does not see
CHECK constraints.

Revision ID: e5f2c9a71b34
Revises: a7d4c92e1f53
Create Date: 2026-10-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f2c9a71b34"
down_revision: str | None = "a7d4c92e1f53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "runs_terminal_stop_reason",
        "runs",
        "state IN ('running','paused','completed') OR stop_reason IS NOT NULL",
        schema="crawl",
    )


def downgrade() -> None:
    op.drop_constraint("runs_terminal_stop_reason", "runs", type_="check", schema="crawl")
