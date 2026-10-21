"""What a fetch asked for and what came back.

These live in `domain/` rather than beside an adapter because three layers
share them: the Fetcher port (both adapters), the extraction chain
(`extract(page, template)` in spec 003 §1) and the scheduler, which reads the
status to decide backoff. A copy per layer is how the render path and the
static path drift apart.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from .enums import FetchPath


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """One URL to fetch, and the politeness already decided for it.

    `user_agent` is required rather than defaulted: ADR-0004 makes honest
    identification a property of every request, and a default here would let
    a code path exist that sends httpx's.
    """

    url: str
    user_agent: str
    timeout_ms: int = 20_000
    headers: Mapping[str, str] = field(default_factory=dict)
    # Rendered fetches only; ignored by the static adapter (spec 012 §1).
    wait_for_selector: str | None = None


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """A response body with the context needed to interpret it.

    `body`, not `html`: the same port fetches `/robots.txt`, which is plain
    text, and spec 002 §5 makes that fetch part of the politeness path rather
    than a special case someone bolts on beside it.

    `fetch_path` records which adapter served it. It does **not** on its own
    reveal an AUTO fallback, which an earlier version of this docstring
    claimed: AUTO fetches static first by design (spec 012 §4), so
    `fetch_path = STATIC` is the healthy outcome as well as the degraded one.
    `fell_back_from` is what distinguishes them.
    """

    request_url: str
    final_url: str
    http_status: int
    body: str
    headers: Mapping[str, str]
    fetched_at: datetime
    elapsed_ms: int
    fetch_path: FetchPath
    # Set only when a path was WANTED and could not be used — today, an AUTO
    # domain whose rendered fetch found the sidecar unavailable (spec 012 §4).
    # `1.11` turns this into `strategy = static_fallback`, which is what
    # TESTING.md §2 asserts when `render` is stopped.
    #
    # It is a field rather than a third `FetchPath` value because `FetchPath`
    # answers "which adapter served this", and rather than adapter state
    # because one adapter serves three concurrent workers. Defaulted, so no
    # existing construction or assertion changes — which is how 1.6's tests
    # stay untouched (BUILD_PLAN 1.7).
    fell_back_from: FetchPath | None = None

    @property
    def degraded(self) -> bool:
        """True when this page is not from the path the domain asked for."""
        return self.fell_back_from is not None

    @property
    def redirected(self) -> bool:
        return self.final_url != self.request_url
