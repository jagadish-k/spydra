"""in_flight >= 0 on crawl.domains

ADR-0026's backstop. `domains.in_flight` gates claiming, so a NEGATIVE value
satisfies `in_flight < max_concurrency` more often than it should and two
workers fetch one host concurrently — rudeness arrived at through the
mechanism meant to prevent it. Spec 002 §2 decrements on completion and §3's
sweep decrements on lease expiry, so the two can race and double-decrement.

**Why this is its own revision rather than an edit to 8c1d4a9f5e02.** It was
first written into that migration, on the reasoning that spec 001 §5 makes
the first migration one unit and there is no production data to preserve.
That was wrong, and a test caught it: both the dev and test databases were
already stamped at 8c1d4a9f5e02, so `alembic upgrade head` had nothing to do
and the constraint never reached either of them. The schema tests then failed
against a database that did not match the migration they were reading.

A migration is a frozen snapshot of a transition — 8c1d4a9f5e02's own
docstring says so, which is what made editing it the wrong move. §5's "one
unit" governs how §1 was first created, not a promise that §1 never gains a
constraint afterwards.

Revision ID: 5b7c0e1a94d3
Revises: 8c1d4a9f5e02
Create Date: 2026-10-18 14:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

from spydra.adapters.postgres.tables import SCHEMA

# revision identifiers, used by Alembic.
revision: str = "5b7c0e1a94d3"
down_revision: str | None = "8c1d4a9f5e02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "in_flight_non_negative"


def upgrade() -> None:
    op.create_check_constraint(CONSTRAINT, "domains", "in_flight >= 0", schema=SCHEMA)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "domains", schema=SCHEMA, type_="check")
