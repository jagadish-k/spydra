"""The Fetcher port (ADR-0008, ADR-0016).

Two real adapters ship in phase 1 behind this one Protocol — `HttpxFetcher`
(1.7) and `RenderServiceFetcher` (1.8) — because a port with one
implementation is an untested abstraction.

The contract is defined here, in the foundation slice, and not by either
adapter. That is what makes the phase's stated requirement achievable: when
1.8 lands, 1.7's tests should need no changes, and they cannot if the first
adapter written was also the thing that decided the shape.

Everything the two adapters disagree about is already named:

- `Backpressure` is raised for a 503 from the render sidecar (spec 002 §6).
  It is not a fetch failure and must not increment `consecutive_failures` —
  a busy sidecar of ours is not a supplier refusing us.
- `FetchFailed` is a request that produced no response.
- An HTTP error status is a *successful* fetch. 403, 429 and 5xx come back as
  a FetchedPage with that status, because deciding what they mean is the
  politeness gate's job (spec 002 §4, ADR-0004) and not an adapter's.
"""

from typing import Protocol

from spydra.domain.enums import FetchPath
from spydra.domain.fetch import FetchedPage, FetchRequest


class Fetcher(Protocol):
    path: FetchPath
    """Which path this adapter is. Lets the scheduler record how a page was
    served without an isinstance check against an adapter it should not know."""

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        """Retrieve one URL.

        Raises:
            Backpressure: the far side is full; requeue without penalty.
            FetchFailed: no response at all (DNS, refused, timeout).
        """
        ...

    async def aclose(self) -> None:
        """Release the connection pool. Both adapters hold one."""
        ...
