"""Baseline for the crawl chain: empty on purpose.

The real crawl schema lands as ONE migration in BUILD_PLAN 1.1 (spec 001 §5:
the first migration creates section 1 in one unit). This revision only pins
the chain so every environment can be proven at head — and `alembic
downgrade -1` has a both-ways story from day one. The crawl schema itself
was created by docker/init-schemas.sql before any migration ran; nothing
here emits CREATE SCHEMA.

Revision ID: 2ff8b22bee8f
Revises:
Create Date: 2026-10-15 17:49:18.285134

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ff8b22bee8f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
