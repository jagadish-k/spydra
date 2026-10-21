"""HTTP adapters for the `Fetcher` port (ADR-0008).

Two real adapters plus the AUTO composition, which is what makes the port a
tested abstraction rather than an untested one (`ports/fetcher.py`):

- `HttpxFetcher` — the static path (BUILD_PLAN 1.6).
- `RenderServiceFetcher` — HTTP to the render sidecar (1.7). No browser
  dependency on this side at all (ADR-0016).
- `AutoFetcher` — static first, the sidecar as the second chance (1.7).
"""

from .auto_fetcher import AutoFetcher
from .httpx_fetcher import HttpxFetcher
from .render_service_fetcher import RenderServiceFetcher

__all__ = ["AutoFetcher", "HttpxFetcher", "RenderServiceFetcher"]
