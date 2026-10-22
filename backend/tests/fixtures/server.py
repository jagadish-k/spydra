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

import base64
import threading
import time
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
    # Spec 012 §3/§6, BUILD_PLAN 1.5: the page opens three dialogs before it
    # writes the product, so a sidecar that does not dismiss them never
    # reaches the content instead of merely taking longer.
    "/katalog/drehmomentschluessel-20-100": PAGES / "mertens/product-dialog.html",
    # Spec 012 §6: image-heavy, for the block_resources comparison. Its
    # images come from SLOW_IMAGE_PREFIX below, which is what makes the
    # difference observable.
    "/catalog/abrasives/discs/rfd-115-060/galerie": (
        PAGES / "vantage-abrasives/product-images.html"
    ),
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

# ---------------------------------------------------------------------------
# Generated responses (BUILD_PLAN 1.5).
#
# Three of spec 012 §6's criteria are about the *size* or the *timing* of a
# response rather than its markup, and none of the three can be a committed
# file: a response that stalls is a property of the server, not of bytes on
# disk, and the oversized one would be a 20 MB blob that the pre-commit hook
# refuses (> 2 MB) and that no reviewer could read. So these are synthesized
# per request, and the shape of each one is a parameter in its URL.
#
# They sit beside ROUTES rather than in it for the same reason TRAP_PREFIX
# does: ROUTES is the explicit contract the tests read, and a generated
# family has no single path to list.
# ---------------------------------------------------------------------------

# /slow/<ms> — sleeps server-side, then answers with a small product page.
# Holds a render context open for a known duration, which is how the context
# cap and the 503 are observed (§6). Server-side rather than a busy page:
# a sleeping socket is deterministic, where "how long does Chromium spend on
# this script" is a measurement of the browser.
SLOW_PREFIX = "/slow/"

# /img/slow/<anything> — a 1x1 PNG behind a fixed delay. The delay is the
# whole mechanism behind "block_resources measurably reduces render time":
# instantly-served images render at the same speed whether blocked or not,
# which would make that criterion unfalsifiable.
SLOW_IMAGE_PREFIX = "/img/slow/"
SLOW_IMAGE_DELAY_S = 0.15

# /oversized/<mb> — <mb> megabytes of HTML, as one text node so the cost is
# transfer and serialization rather than DOM construction. Spec 012 §3 caps
# the response at 10 MB and flags a truncation; asking for 20 exercises it.
OVERSIZED_PREFIX = "/oversized/"
OVERSIZED_MAX_MB = 32  # a bound, so a typo in a test cannot ask for 20 GB

# /generated/<n> — product <n> of an unbounded catalogue, for spec 009 §5's
# "a 1,000-page run at `info` writes fewer than 100 lines" (BUILD_PLAN 1.13).
# A thousand committed files would be a thousand copies of one shape, so the
# page is `vantage-abrasives/product.html` with <n> written into the title,
# the SKU, the price and the image names: every page is a distinct product,
# extracted by the same approved template.
#
# It also sets a session cookie. Spec 009 §1 says no credential is ever
# logged, and a log test over a site that sends none passes against a worker
# that dumps every response header; with this, it cannot.
GENERATED_PREFIX = "/generated/"
GENERATED_TEMPLATE = PAGES / "vantage-abrasives/product.html"
GENERATED_COOKIE_VALUE = "spydra-fixture-session-6f1d2c9a"
GENERATED_SET_COOKIE = f"session={GENERATED_COOKIE_VALUE}; Path=/; HttpOnly"

# Deliberately tiny: the bytes are irrelevant, the delay in front of them is
# the point. 1x1 transparent PNG.
# Split across two literals only so the line is under 100 columns without
# relying on ruff's E501 exemption for a single unsplittable token.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8Dw"
    "HwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def _int_segment(path: str, prefix: str, default: int) -> int:
    """The integer after `prefix`, or `default` when it is absent or junk.

    A bad segment is a default rather than a 400: these URLs are written by
    hand in tests, and a silent 400 would read as a server fault.
    """
    tail = path[len(prefix) :].strip("/").split("/", 1)[0]
    try:
        return int(tail)
    except ValueError:
        return default


def generated_product(n: int) -> bytes:
    """Product <n> of the generated catalogue (see GENERATED_PREFIX)."""
    html = GENERATED_TEMPLATE.read_text()
    html = (
        html.replace("Resin Fibre Disc 115mm P60", f"Resin Fibre Disc 115mm P60 No. {n}")
        .replace("VA-RFD-115-060", f"VA-RFD-115-060-{n}")
        .replace("£14.75", f"£{10 + n % 90}.{n % 100:02d}")
        .replace("/img/rfd-115-060-", f"/img/rfd-115-060-{n}-")
    )
    return html.encode()


class FixtureHandler(BaseHTTPRequestHandler):
    """One handler, no routing framework, no logging to stderr."""

    server_version = "SpydraFixtures/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence. A thousand request lines would bury the test output, and
        a test that needs to know what was requested should assert on the
        server's `requests` list rather than read the console."""

    def _send(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        for name, value in extra_headers:
            self.send_header(name, value)
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

        if path.startswith(SLOW_IMAGE_PREFIX):
            time.sleep(SLOW_IMAGE_DELAY_S)
            self._send(PNG_1X1, "image/png")
            return

        if path.startswith(SLOW_PREFIX):
            time.sleep(_int_segment(path, SLOW_PREFIX, 1000) / 1000)
            body = (
                b'<!doctype html><title>slow</title><div class="produkt">'
                b'<h1 class="produkt__name">Slow Fixture</h1>'
                b'<div class="produkt__preis">GBP 1.00</div></div>'
            )
            self._send(body, "text/html; charset=utf-8")
            return

        if path.startswith(OVERSIZED_PREFIX):
            mb = min(_int_segment(path, OVERSIZED_PREFIX, 20), OVERSIZED_MAX_MB)
            head = b'<!doctype html><title>oversized</title><p id="filler">'
            tail = b"</p>"
            filler = b"x" * (mb * 1024 * 1024 - len(head) - len(tail))
            self._send(head + filler + tail, "text/html; charset=utf-8")
            return

        if path.startswith(GENERATED_PREFIX):
            n = _int_segment(path, GENERATED_PREFIX, 0)
            self._send(
                generated_product(n),
                "text/html; charset=utf-8",
                extra_headers=(("set-cookie", GENERATED_SET_COOKIE),),
            )
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
    # 0.0.0.0 by default so the operator can look at a page from the host.
    # The render sidecar's suite sets 127.0.0.1: that container is on
    # `egress` and `render-link` (ADR-0038), and a fixture site bound on
    # either is a host the browser can resolve. The one sanctioned exception
    # is the `fixtures` service of `make phase1-exit`, behind a profile
    # (ADR-0036), which binds 0.0.0.0 inside its own container on purpose.
    host = os.environ.get("FIXTURE_HOST", "0.0.0.0")  # noqa: S104
    srv = ThreadingHTTPServer((host, port), partial(FixtureHandler))
    srv.requests = []  # type: ignore[attr-defined]
    print(f"fixture site on :{port} — {len(ROUTES)} routes")
    srv.serve_forever()
