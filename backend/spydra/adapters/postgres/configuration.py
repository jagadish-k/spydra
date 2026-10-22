"""Writes a loaded configuration: domains, templates, a run (BUILD_PLAN 1.14).

**One transaction for all of it.** A file that half-applied would leave
templates active with no run, or a run seeded against domains still in
`discovered`, and the operator would have to work out which half happened.

**Templates are versioned, never edited in place** (AGENTS.md rule 12,
ADR-0006). Loading a file again writes the next version of each template and
deactivates the previous active one for the same pattern, which is what
`one_active_per_pattern` requires. Observations keep pointing at the version
that produced them.
"""

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from spydra.domain.enums import DomainEvent, DomainState
from spydra.domain.errors import RefusedConfiguration
from spydra.domain.ids import RunId
from spydra.domain.lifecycle import transition
from spydra.domain.urls import canonical_url, url_hash

if TYPE_CHECKING:
    from spydra.load import DomainConfig

# A new host is inserted `active`: the file is the operator's approval.
_INSERT_DOMAIN = sa.text(
    """
INSERT INTO crawl.domains
    (host, state, render_mode, crawl_delay_ms, configured_crawl_delay_ms, respect_robots)
VALUES (:host, 'active', :render_mode, :delay, :delay, :respect_robots)
ON CONFLICT (host) DO NOTHING
RETURNING id
"""
)

_LOCK_DOMAIN = sa.text(
    "SELECT id, state::text AS state FROM crawl.domains WHERE host = :host FOR UPDATE"
)

# An existing domain keeps its politeness state. The floor is the operator's
# to set, and the live delay is only ever RAISED to meet it: a 429 backoff in
# progress is the site's answer, and a reload is not a reason to forget it
# (spec 002 §4 decays it by successes, never by an edit).
_UPDATE_DOMAIN = sa.text(
    """
UPDATE crawl.domains
SET state = CAST(:state AS crawl.domain_state),
    render_mode = :render_mode,
    configured_crawl_delay_ms = :delay,
    crawl_delay_ms = GREATEST(crawl_delay_ms, :delay),
    respect_robots = :respect_robots
WHERE id = :id
"""
)

# The edges a file may walk. It is an approval, so it can take a candidate
# domain to `active`. It cannot resume a pause (ADR-0004: three 403s are the
# site refusing us, and only a human decides to try again), re-review a
# broken template, or revive an archived domain: those edges belong to an
# operator acting on that specific domain (spec 001 §2).
_APPROVAL_PATH = {
    DomainState.DISCOVERED: (DomainEvent.PROPOSE, DomainEvent.APPROVE),
    DomainState.AWAITING_APPROVAL: (DomainEvent.APPROVE,),
    DomainState.ACTIVE: (),
}

_DEACTIVATE = sa.text(
    """
UPDATE crawl.templates SET is_active = false
WHERE domain_id = :domain_id AND url_pattern = :url_pattern AND is_active
"""
)

_INSERT_TEMPLATE = sa.text(
    """
INSERT INTO crawl.templates
    (domain_id, name, url_pattern, page_kind, version, is_active,
     extraction, discovery, proposed_by, approved_at)
SELECT :domain_id, :name, :url_pattern, :page_kind,
       coalesce(max(version), 0) + 1, true,
       CAST(:extraction AS jsonb), CAST(:discovery AS jsonb), 'human', now()
FROM crawl.templates
WHERE domain_id = :domain_id AND url_pattern = :url_pattern
"""
)

_START_RUN = sa.text(
    "INSERT INTO crawl.runs (domain_ids, trigger) VALUES (:domain_ids, 'manual') RETURNING id"
)

_ENQUEUE = sa.text(
    """
INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash, depth)
VALUES (:run_id, :domain_id, :url, :url_hash, 0)
ON CONFLICT (run_id, url_hash) DO NOTHING
"""
)


class PostgresConfiguration:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def apply(self, domains: Sequence[DomainConfig]) -> RunId:
        async with self._engine.begin() as conn:
            seeded: list[tuple[int, str]] = []
            domain_ids: list[int] = []
            for domain in domains:
                domain_id = await self._domain(conn, domain)
                for row in domain.template_rows():
                    await conn.execute(
                        _DEACTIVATE, {"domain_id": domain_id, "url_pattern": row["url_pattern"]}
                    )
                    await conn.execute(
                        _INSERT_TEMPLATE,
                        {
                            **row,
                            "domain_id": domain_id,
                            "extraction": json.dumps(row["extraction"]),
                            "discovery": json.dumps(row["discovery"]),
                        },
                    )
                domain_ids.append(domain_id)
                seeded.extend((domain_id, url) for url in domain.seeds)

            run_id = RunId(
                (
                    # Every domain the file names, seeds or not: the run's
                    # selection is what the operator loaded.
                    await conn.execute(_START_RUN, {"domain_ids": sorted(set(domain_ids))})
                ).scalar_one()
            )
            for domain_id, url in seeded:
                await conn.execute(
                    _ENQUEUE,
                    {
                        "run_id": int(run_id),
                        "domain_id": domain_id,
                        "url": canonical_url(url),
                        "url_hash": url_hash(url),
                    },
                )
        return run_id

    @staticmethod
    async def _domain(conn: AsyncConnection, domain: DomainConfig) -> int:
        settings = {
            "host": domain.host,
            "render_mode": domain.render_mode.value,
            "delay": domain.crawl_delay_ms,
            "respect_robots": domain.respect_robots,
        }
        inserted = (await conn.execute(_INSERT_DOMAIN, settings)).scalar_one_or_none()
        if inserted is not None:
            return int(inserted)

        row = (await conn.execute(_LOCK_DOMAIN, {"host": domain.host})).one()
        state = DomainState(row.state)
        path = _APPROVAL_PATH.get(state)
        if path is None:
            raise RefusedConfiguration(
                f"{domain.host} is {state.value}. A file cannot move it back to active: "
                "resume a paused domain, or re-review a broken one, as its own decision "
                "(spec 001 §2, ADR-0004). Nothing was written."
            )
        for event in path:
            state = transition(state, event)
        await conn.execute(_UPDATE_DOMAIN, {**settings, "id": row.id, "state": state.value})
        return int(row.id)
