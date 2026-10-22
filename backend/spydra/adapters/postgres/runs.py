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

_STATS = """
jsonb_build_object(
    'queue', (
        SELECT coalesce(jsonb_object_agg(state, n), '{}'::jsonb)
        FROM (SELECT state, count(*) AS n FROM crawl.crawl_queue
              WHERE run_id = :run_id GROUP BY state) s
    ),
    'observations', (SELECT count(*) FROM crawl.page_observations WHERE run_id = :run_id),
    'empty_extractions', (
        SELECT count(*) FROM crawl.page_observations
        WHERE run_id = :run_id AND empty_extraction
    ),
    'unchanged', (
        SELECT count(*) FROM crawl.page_observations WHERE run_id = :run_id AND unchanged
    ),
    'assets_enqueued', (SELECT count(*) FROM crawl.asset_queue WHERE run_id = :run_id)
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
