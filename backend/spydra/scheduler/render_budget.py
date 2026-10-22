"""One budget for every call to the render sidecar (spec 002 §6, ADR-0016).

The rendered pool is sized at or just below `RENDER_CONTEXTS` so the worker
never queues at the sidecar. An AUTO domain's second chance is issued from
the **static** pool, though, so a pool size alone left it outside the budget,
and AUTO domains could oversubscribe the sidecar and manufacture the very
503s the worker treats as backpressure (BUILD_PLAN 1.7 open question 4).

So the budget is a semaphore around the fetcher, not a pool size. Every path
to the sidecar goes through the same instance.

**The wait for a slot is bounded** (`max_wait_s`), and running out of it is
`Backpressure`, the same answer as a full sidecar. The wait happens inside a
claim, and one render can hold a slot for ~80 s (30 s plus headroom, twice
for the single 504 retry). Unbounded, a queue of AUTO second chances could
outlive the 120 s lease, the sweep would hand the row to another worker, and
two workers would fetch one host at once.
"""

import asyncio

from spydra.domain.errors import Backpressure
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.ports.fetcher import Fetcher


class RenderBudget:
    """A `Fetcher` that admits at most `slots` concurrent fetches."""

    def __init__(self, fetcher: Fetcher, slots: int, *, max_wait_s: float = 30.0) -> None:
        self._fetcher = fetcher
        self._slots = asyncio.Semaphore(slots)
        self._max_wait_s = max_wait_s
        self.path = fetcher.path

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self._max_wait_s)
        except TimeoutError:
            raise Backpressure("no render slot within the budget's wait") from None
        try:
            return await self._fetcher.fetch(request)
        finally:
            self._slots.release()

    async def aclose(self) -> None:
        await self._fetcher.aclose()
