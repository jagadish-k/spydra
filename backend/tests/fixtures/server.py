"""The fixture site, served over loopback (BUILD_PLAN 1.4).

Every test and both phase exits run against this instead of the public
internet. A phase gate that depends on a third party's uptime, markup and
tolerance fails for reasons unrelated to the code.

Stdlib only, on purpose: this runs inside the api image and inside the
render sidecar's test network, and adding a web framework to serve eight
static files would be a dependency in two images for no capability.

**It serves `robots.txt` per host.** Politeness is a per-host property (spec
002 §5), so a single fixture host could not exercise `Crawl-delay` as a floor
*and* disallow-all in one run. Request `Host: crawl-delay.test` and that
host's robots is what comes back.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType

FIXTURES = Path(__file__).resolve().parent
PAGES = FIXTURES / "pages"
ROBOTS = FIXTURES / "robots"

# Path → fixture file. Explicit rather than a directory walk: a route table
# is the contract the tests read, and a walk would silently start serving
# whatever someone drops in the folder.
ROUTES: dict[str, Path] = {
    "/catalog/abrasives/discs/": PAGES / "vantage-abrasives/listing.html",
    "/catalog/abrasives/discs/rfd-115-060": PAGES / "vantage-abrasives/product.html",
    "/components/fuse-holder-520-pm": PAGES / "orbis-components/product-jsonld.html",
    "/components/fuse-holder-520-pm-nold": PAGES / "orbis-components/product-stripped.html",
    "/fixings/hex-set-screw-m8x40": PAGES / "northfield/product-redesigned.html",
    "/katalog/stirnlochschluessel-30-80": PAGES / "mertens/product-rendered.html",
    # Soft 404: HTTP **200**, no product. That status is the whole point
    # (ADR-0030) — serving 404 here would make the fixture test nothing.
    "/katalog/discontinued-item": PAGES / "mertens/product-missing.html",
}

# Host → which robots.txt that host answers with.
ROBOTS_BY_HOST: dict[str, Path] = {
    "crawl-delay.test": ROBOTS / "crawl-delay.txt",
    "disallow-all.test": ROBOTS / "disallow-all.txt",
}
DEFAULT_ROBOTS = ROBOTS / "permissive.txt"

# A repeating path that generates URLs for ever, for BUILD_PLAN 2.5's trap
# defences. Unbounded on purpose: the caps must be what stops it, not the
# fixture running out of pages.
TRAP_PREFIX = "/trap/"


class FixtureHandler(BaseHTTPRequestHandler):
    """One handler, no routing framework, no logging to stderr."""

    server_version = "SpydraFixtures/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence. A thousand request lines would bury the test output, and
        a test that needs to know what was requested should assert on the
        server's `requests` list rather than read the console."""

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        path = self.path.split("?", 1)[0]
        host = (self.headers.get("host") or "").split(":", 1)[0]
        self.server.requests.append((host, self.path))  # type: ignore[attr-defined]

        if path == "/robots.txt":
            which = ROBOTS_BY_HOST.get(host, DEFAULT_ROBOTS)
            self._send(which.read_bytes(), "text/plain; charset=utf-8")
            return

        if path.startswith(TRAP_PREFIX):
            depth = path.count("/")
            body = (
                f"<!doctype html><title>trap depth {depth}</title>"
                f'<a href="{path.rstrip("/")}/deeper/">deeper</a>'
            ).encode()
            self._send(body, "text/html; charset=utf-8")
            return

        target = ROUTES.get(path)
        if target is None:
            self._send(b"<!doctype html><title>404</title>", "text/html; charset=utf-8", 404)
            return

        self._send(target.read_bytes(), "text/html; charset=utf-8")


class FixtureSite:
    """A context manager around the server, so a test cannot leak a thread.

    `base_url` is loopback and the port is chosen by the OS — a fixed port
    makes two test files in one suite flaky for reasons that look like
    network trouble.
    """

    def __init__(self, host: str = "127.0.0.1") -> None:
        # Kept rather than read back from `server_address`, whose type admits
        # bytes — mypy is right to object, and we already know the host.
        self._host = host
        self._server = ThreadingHTTPServer((host, 0), partial(FixtureHandler))
        self._server.requests = []  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://{self._host}:{port}"

    @property
    def requests(self) -> list[tuple[str, str]]:
        """(host, path) per request, in order — for asserting on politeness."""
        return self._server.requests  # type: ignore[attr-defined,no-any-return]

    def __enter__(self) -> FixtureSite:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


if __name__ == "__main__":
    # `python -m tests.fixtures.server` — for the render sidecar's suite and
    # for looking at a page by hand.
    import os

    port = int(os.environ.get("FIXTURE_PORT", "8099"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), partial(FixtureHandler))  # noqa: S104
    srv.requests = []  # type: ignore[attr-defined]
    print(f"fixture site on :{port} — {len(ROUTES)} routes")
    srv.serve_forever()
