"""The end of a run (BUILD_PLAN 1.13, spec 009 §5).

A run is finished when its queue has nothing left to claim and nothing in
flight. No process owns "the run" (any worker can close its last row), so the
finish is one guarded `UPDATE` that only the first worker to see the drained
queue gets a row back from. That is the one that logs it.

**`stats` is computed in the same statement**, from the rows themselves
rather than from counters a worker kept: spec 009 §5 wants it populated "on
completion, stop and failure alike", and in-process counters die with the
process that held them. `2.x`'s stop and failure paths reuse `_STATS`.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.domain.ids import RunId

# Spec 009 §2's shape, for the keys phase 1 can know. `assets_downloaded`,
# `asset_bytes` and `dedupe_rate` arrive with the asset pool (5.2), and
# `validation_pass_rate` with the reports (5.7); `assets_enqueued` stands in
# until then. `by_strategy` counts the rung that produced the fields (the
# `extraction_rung` column, so a static fallback still counts as the rung it
# used), and `failed` is the rows that never produced an observation.
_STATS = """
jsonb_build_object(
    'pages_crawled', (SELECT count(*) FROM crawl.crawl_queue
                      WHERE run_id = :run_id AND state = 'done'),
    'pages_failed', (SELECT count(*) FROM crawl.crawl_queue
                     WHERE run_id = :run_id AND state = 'failed'),
    'pages_abandoned', (SELECT count(*) FROM crawl.crawl_queue
                        WHERE run_id = :run_id AND state = 'abandoned'),
    'pages_changed', (SELECT count(*) FROM crawl.page_observations
                      WHERE run_id = :run_id AND NOT unchanged AND content_hash IS NOT NULL),
    'empty_extractions', (SELECT count(*) FROM crawl.page_observations
                          WHERE run_id = :run_id AND empty_extraction),
    'assets_enqueued', (SELECT count(*) FROM crawl.asset_queue WHERE run_id = :run_id),
    'by_strategy', (
        SELECT coalesce(jsonb_object_agg(rung, n), '{}'::jsonb)
        FROM (
            SELECT coalesce(extraction_rung, 'none') AS rung, count(*) AS n
            FROM crawl.page_observations WHERE run_id = :run_id GROUP BY 1
            UNION ALL
            SELECT 'failed', count(*) FROM crawl.crawl_queue
            WHERE run_id = :run_id AND state = 'failed'
        ) s
    ),
    'by_domain', (
        SELECT coalesce(jsonb_object_agg(d.host, jsonb_build_object(
                   'crawled', s.crawled, 'failed', s.failed)), '{}'::jsonb)
        FROM (
            SELECT domain_id,
                   count(*) FILTER (WHERE state = 'done') AS crawled,
                   count(*) FILTER (WHERE state = 'failed') AS failed
            FROM crawl.crawl_queue WHERE run_id = :run_id GROUP BY domain_id
        ) s
        JOIN crawl.domains d ON d.id = s.domain_id
    ),
    'duration_s', (SELECT round(extract(epoch FROM now() - started_at))::int
                   FROM crawl.runs WHERE id = :run_id)
)
"""

_FINISH_IF_DRAINED = sa.text(
    f"""
UPDATE crawl.runs
SET state = 'completed', finished_at = now(), stats = {_STATS}
WHERE id = :run_id
  AND state = 'running'
  AND NOT EXISTS (
      SELECT 1 FROM crawl.crawl_queue
      WHERE run_id = :run_id AND state IN ('pending', 'in_flight')
  )
RETURNING stats
"""
)


# Every running run whose queue has drained. For the lease sweep: a row it
# retires to `failed` (a worker SIGKILLed on the run's last row, third
# attempt) is closed by no worker, so without this the run stayed `running`
# for ever.
_FINISH_DRAINED = sa.text(
    f"""
UPDATE crawl.runs r
SET state = 'completed', finished_at = now(),
    stats = {_STATS.replace(":run_id", "r.id")}
WHERE r.state = 'running'
  -- A run that has not enqueued anything yet is not drained, it is new.
  AND EXISTS (SELECT 1 FROM crawl.crawl_queue WHERE run_id = r.id)
  AND NOT EXISTS (
      SELECT 1 FROM crawl.crawl_queue
      WHERE run_id = r.id AND state IN ('pending', 'in_flight')
  )
RETURNING r.id, r.stats
"""
)


class PostgresRuns:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def finish_if_drained(self, run_id: RunId) -> dict[str, Any] | None:
        """The run's stats if THIS call finished it, else `None`."""
        async with self._engine.begin() as conn:
            stats = (
                await conn.execute(_FINISH_IF_DRAINED, {"run_id": int(run_id)})
            ).scalar_one_or_none()
        return dict(stats) if stats is not None else None

    async def finish_drained(self) -> list[tuple[RunId, dict[str, Any]]]:
        """Finish every running run with nothing left to claim; the runs
        THIS call finished, with their stats."""
        async with self._engine.begin() as conn:
            rows = (await conn.execute(_FINISH_DRAINED)).all()
        return [(RunId(row.id), dict(row.stats)) for row in rows]
