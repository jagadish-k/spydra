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
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.domain.ids import RunId

if TYPE_CHECKING:
    from spydra.load import DomainConfig

# `crawl_delay_ms` is set from the operator's value too: a file that says
# 5000 means the next request waits 5 s, not whatever backoff the column holds.
_UPSERT_DOMAIN = sa.text(
    """
INSERT INTO crawl.domains
    (host, state, render_mode, crawl_delay_ms, configured_crawl_delay_ms, respect_robots)
VALUES (:host, 'active', :render_mode, :delay, :delay, :respect_robots)
ON CONFLICT (host) DO UPDATE
SET state = 'active',
    render_mode = EXCLUDED.render_mode,
    crawl_delay_ms = EXCLUDED.crawl_delay_ms,
    configured_crawl_delay_ms = EXCLUDED.configured_crawl_delay_ms,
    respect_robots = EXCLUDED.respect_robots
RETURNING id
"""
)

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
                domain_id = int(
                    (
                        await conn.execute(
                            _UPSERT_DOMAIN,
                            {
                                "host": domain.host,
                                "render_mode": domain.render_mode.value,
                                "delay": domain.crawl_delay_ms,
                                "respect_robots": domain.respect_robots,
                            },
                        )
                    ).scalar_one()
                )
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
                        "url": url,
                        "url_hash": url_hash(url),
                    },
                )
        return run_id
