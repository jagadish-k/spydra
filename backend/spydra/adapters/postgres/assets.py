"""`asset_queue` writes and its depth (BUILD_PLAN 1.12, spec 008 §1 step 1).

**Enqueue only. Nothing here fetches an image**, and that is the whole point
of ADR-0003: "assets are enqueued, not fetched inline: a page worker extracts
image URLs, inserts `asset_queue` rows and moves on. It never blocks on an
image." There is no `Fetcher` in this module and there must never be one —
the pool that drains the queue, the `AssetGate` and the `AssetStore` are
`5.2` (spec 008's own header says so).

So a page with 24 images costs one `INSERT`, not 24 downloads. The test for
that is a timing one against `1.4`'s deliberately slow image route, because a
test that counted rows would pass against an enqueue that downloaded every
image first.
"""

from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.domain.ids import ObservationId, RunId

# One statement for every image on the page. `ON CONFLICT DO NOTHING` against
# the UNIQUE (observation_id, source_url) spec 001 §1 already defines: a
# gallery that lists its hero image twice is a conflict, not a duplicate row,
# and a re-crawl that re-enqueues is a no-op rather than an error.
#
# `unnest` with ordinality rather than a VALUES list built in Python: the
# statement is then one prepared shape whatever the image count, so a
# 24-image page and a 1-image page are the same plan.
#
# The position is offset by whatever this observation already has rather than
# restarting at 0. The writer enqueues a page's whole gallery in ONE call, so
# in the ordinary path the offset is 0 — but a second call for the same
# observation numbered its rows 0,1,2 again, and `5.2` copies this column
# into `observation_assets.position`, where two rows at position 0 are a
# gallery in an undefined order. Found by a test that drained "position 0"
# and hit two rows.
_ENQUEUE = sa.text(
    """
INSERT INTO crawl.asset_queue
    (run_id, observation_id, source_url, source_host, position)
SELECT :run_id, :observation_id, u.url, u.host,
       u.position - 1 + coalesce(
           (SELECT max(position) + 1
            FROM crawl.asset_queue
            WHERE observation_id = :observation_id),
           0)
FROM unnest(CAST(:urls AS text[]), CAST(:hosts AS text[]))
     WITH ORDINALITY AS u(url, host, position)
ON CONFLICT (observation_id, source_url) DO NOTHING
"""
)

# Spec 002 §7's number. Served by `ix_asset_queue_pending_host`, which is
# partial on `state = 'pending'` — so this counts an index over the pending
# rows rather than scanning a queue that keeps every row it ever drained.
_PENDING = sa.text("SELECT count(*) FROM crawl.asset_queue WHERE state = 'pending'")


class PostgresAssets:
    """Inserts `asset_queue` rows and answers how deep the queue is."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def enqueue(
        self, run_id: RunId, observation_id: ObservationId, urls: tuple[str, ...]
    ) -> int:
        """One row per URL, in order. Returns how many were inserted.

        The count is the INSERTED rows, not the URLs offered: a re-crawl of
        an unchanged page enqueues nothing and says 0, which is the number
        `1.13`'s log and `2.8`'s progress event should carry.
        """
        if not urls:
            # No statement at all for a page with no images, which is most
            # listing pages. An empty `unnest` would be a round trip to
            # insert nothing.
            return 0

        async with self._engine.begin() as conn:
            result = await conn.execute(
                _ENQUEUE,
                {
                    "run_id": int(run_id),
                    "observation_id": int(observation_id),
                    "urls": list(urls),
                    "hosts": [_host(url) for url in urls],
                },
            )
        return result.rowcount

    async def pending(self) -> int:
        """How many assets are waiting (spec 002 §7's backpressure input)."""
        async with self._engine.connect() as conn:
            return int((await conn.execute(_PENDING)).scalar_one())


def _host(url: str) -> str:
    """`asset_queue.source_host` is `NOT NULL` and `5.2`'s `AssetGate` keys
    its per-host semaphore on it (spec 002 §6).

    Lowercased, port dropped: `CDN.example.test` and `cdn.example.test:443`
    are one host, and a gate keyed on the raw string would give the same CDN
    several independent concurrency budgets — which is how a polite crawler
    hammers one origin. An unparseable URL yields `""` rather than raising:
    the column is NOT NULL, the row still belongs in the queue, and `5.2`
    rejects it on the bytes.
    """
    return (urlsplit(url).hostname or "").lower()
