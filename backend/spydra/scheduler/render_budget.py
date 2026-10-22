"""One budget for every call to the render sidecar (spec 002 §6, ADR-0016).

The rendered pool is sized at or just below `RENDER_CONTEXTS` so the worker
never queues at the sidecar. An AUTO domain's second chance is issued from
the **static** pool, though, so a pool size alone left it outside the budget,
and AUTO domains could oversubscribe the sidecar and manufacture the very
503s the worker treats as backpressure (BUILD_PLAN 1.7 open question 4).

So the budget is a semaphore around the fetcher, not a pool size. Every path
to the sidecar goes through the same instance.
"""

import asyncio

from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.ports.fetcher import Fetcher


class RenderBudget:
    """A `Fetcher` that admits at most `slots` concurrent fetches."""

    def __init__(self, fetcher: Fetcher, slots: int) -> None:
        self._fetcher = fetcher
        self._slots = asyncio.Semaphore(slots)
        self.path = fetcher.path

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        async with self._slots:
            return await self._fetcher.fetch(request)

    async def aclose(self) -> None:
        await self._fetcher.aclose()
