"""Row builders for the frontier suites (BUILD_PLAN 1.8).

Shared by the single-worker and the two-worker files rather than copied:
both need a run and a domain, and two copies of "what an eligible domain
looks like" would let one suite keep passing after the eligibility rules
changed.

Everything here COMMITS. The frontier opens its own transactions (ADR-0026
requires the claim to be one short transaction, not one held across a
fetch), so it cannot see a test's uncommitted rows.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.domain.ids import DomainId, RunId


async def seed_domain(
    engine: AsyncEngine,
    host: str = "vantage-abrasives.test",
    *,
    state: str = "active",
    max_concurrency: int = 1,
    in_flight: int = 0,
    next_eligible_at: datetime | None = None,
    crawl_delay_ms: int = 2000,
) -> DomainId:
    """A domain that is eligible by default.

    Defaults chosen so a test has to *opt out* of eligibility to test
    ineligibility — the opposite way round, every test would be one forgotten
    field away from passing because nothing was claimable.
    """
    due = next_eligible_at
    if due is None:
        due = datetime.now(UTC) - timedelta(minutes=1)
    async with engine.begin() as conn:
        return DomainId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.domains
                            (host, state, max_concurrency, in_flight,
                             next_eligible_at, crawl_delay_ms)
                        VALUES (:host, CAST(:state AS crawl.domain_state), :mc, :inf,
                                :due, :delay)
                        RETURNING id
                        """
                    ),
                    {
                        "host": host,
                        "state": state,
                        "mc": max_concurrency,
                        "inf": in_flight,
                        "due": due,
                        "delay": crawl_delay_ms,
                    },
                )
            ).scalar_one()
        )


async def seed_run(engine: AsyncEngine, domain_ids: list[int]) -> RunId:
    async with engine.begin() as conn:
        return RunId(
            (
                await conn.execute(
                    sa.text("INSERT INTO crawl.runs (domain_ids) VALUES (:ids) RETURNING id"),
                    {"ids": domain_ids},
                )
            ).scalar_one()
        )


async def seed_queue_row(
    engine: AsyncEngine,
    run_id: RunId,
    domain_id: DomainId,
    url: str,
    *,
    depth: int = 0,
    state: str = "pending",
    attempts: int = 0,
    locked_until: datetime | None = None,
) -> int:
    async with engine.begin() as conn:
        return int(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.crawl_queue
                            (run_id, domain_id, url, url_hash, depth, state,
                             attempts, locked_until)
                        VALUES (:run, :dom, :url, :hash, :depth, :state, :attempts, :locked)
                        RETURNING id
                        """
                    ),
                    {
                        "run": int(run_id),
                        "dom": int(domain_id),
                        "url": url,
                        "hash": url_hash(url),
                        "depth": depth,
                        "state": state,
                        "attempts": attempts,
                        "locked": locked_until,
                    },
                )
            ).scalar_one()
        )


async def domain_row(engine: AsyncEngine, domain_id: DomainId) -> sa.Row[tuple[int, int, int]]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    """
                    SELECT in_flight, consecutive_failures, crawl_delay_ms,
                           next_eligible_at, state::text AS state
                    FROM crawl.domains WHERE id = :id
                    """
                ),
                {"id": int(domain_id)},
            )
        ).one()


async def queue_row(engine: AsyncEngine, item_id: int) -> sa.Row[tuple[str, int]]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT state, attempts, locked_until FROM crawl.crawl_queue WHERE id = :id"
                ),
                {"id": item_id},
            )
        ).one()
