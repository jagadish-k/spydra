"""The domain row as the crawl path reads it (BUILD_PLAN 1.13).

**Not a port** (ADR-0008): repositories for domains, pages, templates and runs
are ordinary code. The politeness state is *written* by the frontier, in the
transaction that closes the queue row (spec 002 §2); this only reads it, and
moves the lifecycle on the one edge the crawl path owns (ADR-0004's `BLOCK`).
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.domain.entities import Domain
from spydra.domain.enums import DomainEvent, DomainState, RenderMode
from spydra.domain.ids import DomainId
from spydra.domain.lifecycle import can, transition

_GET = sa.text(
    """
SELECT id, host, state::text AS state, render_mode, crawl_delay_ms,
       configured_crawl_delay_ms, max_concurrency, asset_concurrency,
       respect_robots, next_eligible_at, consecutive_failures,
       consecutive_403s, user_agent, max_depth, deny_patterns
FROM crawl.domains
WHERE id = :id
"""
)

# The state is read under a row lock, so two workers that both see a third
# 403 move the domain once and the second sees an edge that no longer exists.
_LOCK_STATE = sa.text("SELECT state::text FROM crawl.domains WHERE id = :id FOR UPDATE")

_SET_STATE = sa.text(
    "UPDATE crawl.domains SET state = CAST(:state AS crawl.domain_state) WHERE id = :id"
)


class PostgresDomains:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, domain_id: DomainId) -> Domain:
        async with self._engine.connect() as conn:
            row = (await conn.execute(_GET, {"id": int(domain_id)})).mappings().one()
        return Domain(
            id=DomainId(row["id"]),
            host=row["host"],
            state=DomainState(row["state"]),
            render_mode=RenderMode(row["render_mode"]),
            crawl_delay_ms=row["crawl_delay_ms"],
            configured_crawl_delay_ms=row["configured_crawl_delay_ms"],
            max_concurrency=row["max_concurrency"],
            asset_concurrency=row["asset_concurrency"],
            respect_robots=row["respect_robots"],
            next_eligible_at=row["next_eligible_at"],
            consecutive_failures=row["consecutive_failures"],
            consecutive_403s=row["consecutive_403s"],
            user_agent=row["user_agent"],
            max_depth=row["max_depth"],
            deny_patterns=tuple(row["deny_patterns"]),
        )

    async def apply(self, domain_id: DomainId, event: DomainEvent) -> DomainState | None:
        """Move the domain along `event`'s edge, or return `None` if the edge
        does not exist from where it is now (another worker got there first,
        or the operator paused it mid-run)."""
        async with self._engine.begin() as conn:
            state = DomainState(
                (await conn.execute(_LOCK_STATE, {"id": int(domain_id)})).scalar_one()
            )
            if not can(state, event):
                return None
            moved = transition(state, event)
            await conn.execute(_SET_STATE, {"id": int(domain_id), "state": moved.value})
        return moved
