"""HTTP adapters for the `Fetcher` port (ADR-0008).

`HttpxFetcher` is the static path (BUILD_PLAN 1.6). `RenderServiceFetcher`
(1.7) talks to the sidecar and lands beside it behind the same port.
"""

from .httpx_fetcher import HttpxFetcher

__all__ = ["HttpxFetcher"]
