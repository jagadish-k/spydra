"""`RenderBudget`: one cap on concurrent calls to the render sidecar
(BUILD_PLAN 1.13, spec 002 §6, 1.7 open question 4).

Observed with a fake `Fetcher` that counts how many fetches are inside it at
once, not by inspecting the semaphore: the claim is about calls reaching the
sidecar, and that is what the fake stands in for.
"""

import asyncio
from datetime import UTC, datetime

from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.scheduler.render_budget import RenderBudget

UA = "SpydraTest/1.0 (+https://spydra.test)"


class ConcurrencyRecordingFetcher:
    """A sidecar stand-in that records the most fetches it held at once."""

    path = FetchPath.RENDERED

    def __init__(self, hold_s: float = 0.05, raises: Exception | None = None) -> None:
        self._hold_s = hold_s
        self.raises = raises
        self.inside = 0
        self.peak = 0
        self.calls = 0
        self.closed = False

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        self.calls += 1
        self.inside += 1
        self.peak = max(self.peak, self.inside)
        try:
            await asyncio.sleep(self._hold_s)
            if self.raises is not None:
                raise self.raises
            return FetchedPage(
                request_url=request.url,
                final_url=request.url,
                http_status=200,
                body="<p>rendered</p>",
                headers={},
                fetched_at=datetime.now(UTC),
                elapsed_ms=int(self._hold_s * 1000),
                fetch_path=self.path,
            )
        finally:
            self.inside -= 1

    async def aclose(self) -> None:
        self.closed = True


def _request(n: int) -> FetchRequest:
    return FetchRequest(url=f"https://mertens.test/katalog/{n}", user_agent=UA)


async def test_no_more_fetches_than_slots_are_ever_in_flight_at_once() -> None:
    sidecar = ConcurrencyRecordingFetcher()
    budget = RenderBudget(sidecar, 2)

    pages = await asyncio.gather(*(budget.fetch(_request(n)) for n in range(8)))

    assert len(pages) == 8 and sidecar.calls == 8
    assert sidecar.peak <= 2
    # And it is a cap, not a serialiser: two did run together.
    assert sidecar.peak == 2


async def test_a_slot_is_given_back_when_the_sidecar_raises() -> None:
    """Backpressure is the common failure here. A slot leaked on each one
    would shrink the budget to nothing and stall every rendered domain."""
    sidecar = ConcurrencyRecordingFetcher(raises=Backpressure())
    budget = RenderBudget(sidecar, 2)

    results = await asyncio.gather(
        *(budget.fetch(_request(n)) for n in range(6)), return_exceptions=True
    )
    assert all(isinstance(r, Backpressure) for r in results)

    sidecar.raises = None
    sidecar.peak = 0
    done = await asyncio.wait_for(
        asyncio.gather(*(budget.fetch(_request(n)) for n in range(2))), timeout=2
    )
    assert len(done) == 2
    assert sidecar.peak == 2, "a slot was lost to an exception"


async def test_closing_the_budget_closes_the_sidecar_client() -> None:
    sidecar = ConcurrencyRecordingFetcher()
    await RenderBudget(sidecar, 2).aclose()
    assert sidecar.closed
