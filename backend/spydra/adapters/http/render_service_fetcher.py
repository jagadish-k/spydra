"""The rendered fetch path — `Fetcher` over the render sidecar (BUILD_PLAN 1.7).

The Python side has **no browser dependency at all** (ADR-0016): this is an
HTTP client against the service specified in spec 012, and the only thing it
knows about Playwright is that something on the other end has one.

Like `HttpxFetcher`, it decides nothing about what a supplier's status means.
Unlike it, it has to translate the *sidecar's* status table (spec 012 §1),
and one of those codes is not a failure at all:

| Sidecar | Means                              | Here                        |
| ------- | ---------------------------------- | --------------------------- |
| 200     | rendered                           | `FetchedPage`               |
| 422     | malformed request — our bug        | `FetchFailed`, no retry     |
| 502     | navigation failed (DNS, refused)   | `FetchFailed`, no retry     |
| 503     | no context within the queue window | **`Backpressure`**          |
| 504     | render timed out                   | retry once, then `FetchFailed` |

**503 is the one to get right.** It means *our own* sidecar is full, so the
row returns to `pending` with no `consecutive_failures`, no backoff and no
attempt charged (spec 002 §6). Treating it as a fetch failure would walk a
perfectly healthy supplier toward an ADR-0004 pause because a browser of ours
was busy.

**The single 504 retry is deliberate and is not a retry through a block.**
ADR-0004 forbids retrying a supplier that has refused us — a 403 or a 429.
Neither ever arrives here: this adapter talks only to the sidecar, and a
render timeout is a property of our browser. Spec 012 §1 asks for exactly one
retry, and spec 012 §1's "the sidecar does not retry and does not back off"
is about the sidecar's own behaviour, not its client's.
"""

from typing import Any

import httpx2

from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.ports.clock import Clock

# Spec 012 §2's default. Sent explicitly rather than relying on the sidecar's
# own default, so the two cannot drift apart silently.
DEFAULT_BLOCK_RESOURCES = ("image", "font", "media")

# Spec 012 §1. Exactly one, and only for 504.
RENDER_TIMEOUT_RETRIES = 1

# "The sidecar cannot serve right now", as opposed to "this page did not
# render". Requeue with no penalty (spec 002 §6).
BACKPRESSURE_STATUSES = frozenset({503, 500})

# The keys spec 012 §1 promises in a 200. Absent any of them the sidecar has
# broken its own contract, and the honest answer is to fail the page — NOT to
# default them. `payload.get("status", 0)` and `payload.get("html", "")` were
# the first version, and they turn a sidecar regression into a page that
# looks real: empty body, status 0. The extraction chain then scores
# `empty_extraction` on every page and 1.11 moves healthy domains to BROKEN
# past 20% — a payload bug on OUR side, charged to the supplier. Status 0 also
# appears in no row of spec 002 §4's table, so the gate has no branch for it
# and `consecutive_failures` never resets.
REQUIRED_PAYLOAD_KEYS = ("html", "status", "final_url")

# Spec 012 §3's hard ceiling, enforced by the sidecar itself
# (`render/src/limits.js::MAX_TIMEOUT_MS`). Clamped HERE as well, because
# asking for more buys nothing — the sidecar will not spend it, and the
# adapter would sit waiting for a budget that cannot be used.
SIDECAR_MAX_TIMEOUT_MS = 30_000

# The sidecar's render budget, plus its 5 s context-queue wait (spec 012 §2),
# plus room to answer. All three: a transport timeout that fires before the
# sidecar can reply 503 or 504 reports a fetch failure when the sidecar was
# about to say something more useful, and the queue wait is the part that is
# easy to forget because it happens before rendering starts.
TRANSPORT_HEADROOM_S = 10.0

# Spec 002 §1's lease. NOT imported from the frontier — that adapter is
# BUILD_PLAN 1.8 and this one must not depend on it — so it is duplicated
# with this comment, and a test asserts the arithmetic.
#
# The point: two attempts must finish well inside the lease. If one fetch can
# outlive it, the sweep returns the row to `pending` while the fetch is still
# in flight and another worker takes the same URL — two simultaneous requests
# to one host, which is what ADR-0026 exists to prevent, reached through the
# mechanism meant to prevent it.
LEASE_BUDGET_S = 120


class RenderServiceFetcher:
    """`Fetcher` over the render sidecar's `POST /render`.

    The base URL comes from `RENDER_BASE_URL`, which points at the **host
    loopback** rather than a container name: `render` is alone on the
    `egress` network and nothing internal resolves from it (ADR-0023). That
    is a compose concern, not this adapter's — it is passed a URL.
    """

    path = FetchPath.RENDERED

    def __init__(
        self,
        base_url: str,
        clock: Clock,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._clock = clock
        self._client = client if client is not None else self.build_client()

    @staticmethod
    def build_client(transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
        """The production client. `transport` is the test seam.

        Public and transport-taking for the same reason as `HttpxFetcher`'s:
        a suite that restates this configuration is a suite that cannot see
        anything later added to it.

        No `follow_redirects` — the sidecar is one known endpoint and a
        redirect from it would be a misconfiguration, not something to chase.
        `trust_env=False` so an ambient proxy cannot sit between the worker
        and a service on our own loopback.
        """
        return httpx2.AsyncClient(transport=transport, trust_env=False)

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        """Render one URL through the sidecar.

        Raises:
            Backpressure: the sidecar is full or unreachable. Requeue without
                penalty; the domain is not at fault.
            FetchFailed: the sidecar rendered nothing and will not on a retry.
        """
        started = self._clock.monotonic()
        attempts = RENDER_TIMEOUT_RETRIES + 1

        for attempt in range(attempts):
            response = await self._post(request)

            if response.status_code == 200:
                return self._page(request, response, started)

            if response.status_code in BACKPRESSURE_STATUSES:
                # 503 is spec 012 §1's "no context within the queue window".
                #
                # 500 is not in that table, and it is the sidecar's own "I
                # cannot serve": `render/src/index.js` answers 500 when the
                # browser will not launch or a context cannot be created — a
                # /dev/shm-starved Chromium that fails to relaunch after a
                # recycle answers 500 to every request. That is the condition
                # spec 012 §4 and ADR-0016 answer with "rows stay pending,
                # reported stalled, NOT failed", so it is backpressure for
                # the same reason an unreachable sidecar is.
                #
                # Charged to the supplier instead, it would mark healthy
                # domains failed because a browser of ours is broken — and
                # AutoFetcher, which falls back on Backpressure, would not
                # fall back at all.
                raise Backpressure(
                    f"{request.url}: render sidecar cannot serve "
                    f"({response.status_code}): {self._error_of(response)}"
                )

            if response.status_code == 504 and attempt < attempts - 1:
                continue

            raise FetchFailed(
                f"{request.url}: render sidecar returned {response.status_code}: "
                f"{self._error_of(response)}"
            )

        # Unreachable: the loop either returns or raises on its last pass.
        raise AssertionError("render retry loop fell through")  # pragma: no cover

    async def _post(self, request: FetchRequest) -> httpx2.Response:
        try:
            return await self._client.post(
                f"{self._base_url}/render",
                json=self._body(request),
                timeout=self._transport_timeout_s(request),
            )
        except httpx2.InvalidURL as exc:
            # A malformed RENDER_BASE_URL is a permanent misconfiguration of
            # ours and must not look transient: as Backpressure it would
            # requeue every rendered row for ever, with no failure count, no
            # backoff, no error and no run completion. It belongs with 422.
            #
            # `UnicodeError` is deliberately NOT here, unlike in
            # HttpxFetcher: there the user-agent goes into an HTTP *header*,
            # which httpx2 encodes as ASCII, while here it goes into a JSON
            # body, which encodes any string. Copying that tuple across
            # without its reasoning would have added an unreachable branch.
            raise FetchFailed(
                f"{request.url}: render sidecar URL is malformed ({self._base_url!r}): {exc}"
            ) from exc
        except httpx2.HTTPError as exc:
            # The sidecar is down, not the supplier. Spec 012 §4: a RENDERED
            # domain's rows stay `pending` and the run reports them stalled
            # rather than failed — which is Backpressure's contract, not
            # FetchFailed's. Calling this a fetch failure would charge a
            # healthy domain for our own service being stopped, and three of
            # those is an ADR-0004 pause.
            raise Backpressure(
                f"{request.url}: render sidecar unreachable: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _render_timeout_ms(request: FetchRequest) -> int:
        """The render budget, clamped to the sidecar's own ceiling."""
        return min(request.timeout_ms, SIDECAR_MAX_TIMEOUT_MS)

    @classmethod
    def _transport_timeout_s(cls, request: FetchRequest) -> float:
        """How long to wait on the socket.

        Always passed explicitly. httpx2's default is **5 seconds**
        (measured), so dropping this argument would silently cap every render
        at 5 s: RENDERED domains would stall for ever and AUTO domains
        degrade for ever, with nothing logged as an error.
        """
        return cls._render_timeout_ms(request) / 1000 + TRANSPORT_HEADROOM_S

    def _body(self, request: FetchRequest) -> dict[str, Any]:
        """The spec 012 §1 request body.

        `wait_for_selector` is omitted rather than sent as null when the
        request has none: the sidecar validates it as a non-empty string and
        answers 422 otherwise, which this adapter would then report as a bug
        in itself.
        """
        body: dict[str, Any] = {
            "url": request.url,
            "wait_until": "networkidle",
            "timeout_ms": self._render_timeout_ms(request),
            "block_resources": list(DEFAULT_BLOCK_RESOURCES),
            # ADR-0004 applies to the rendered path too — the browser
            # identifies itself as us, not as Chrome.
            "user_agent": request.user_agent,
        }
        if request.headers:
            body["extra_headers"] = dict(request.headers)
        if request.wait_for_selector is not None:
            body["wait_for_selector"] = request.wait_for_selector
        return body

    def _page(
        self,
        request: FetchRequest,
        response: httpx2.Response,
        started: float,
    ) -> FetchedPage:
        payload = self._payload(request, response)
        return FetchedPage(
            request_url=request.url,
            # The sidecar's `final_url`, not the transport's: the redirect
            # happened in the browser, so httpx2 never saw it and
            # `response.url` is the sidecar's own /render endpoint.
            final_url=str(payload["final_url"]),
            # Likewise the status: `response.status_code` is the sidecar
            # saying "I rendered something" (200), while `payload["status"]`
            # is what the SUPPLIER said — which is the one the politeness
            # gate reads.
            http_status=int(payload["status"]),
            body=str(payload["html"]),
            headers={},
            fetched_at=self._clock.now(),
            elapsed_ms=int((self._clock.monotonic() - started) * 1000),
            fetch_path=self.path,
        )

    def _payload(self, request: FetchRequest, response: httpx2.Response) -> dict[str, Any]:
        """The 200 body, or `FetchFailed` — never a defaulted page.

        Four ways a 200 can fail to be a rendered page, all measured against
        a real response: a body that is not JSON (`JSONDecodeError`), a body
        that is a JSON list (`AttributeError` on `.get`), a missing key, and
        a key present but null (`TypeError` from `int(None)`).

        None of those is in the port's vocabulary. `ports/fetcher.py` promises
        `Backpressure` or `FetchFailed` and nothing else, so a bare
        `JSONDecodeError` would travel up through `1.13`'s TaskGroup, leave
        `in_flight` incremented and the row leased, and stall the domain
        until the 120-second sweep — one bad response taking a domain down.
        """
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchFailed(
                f"{request.url}: render sidecar returned 200 with a body that is not JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise FetchFailed(
                f"{request.url}: render sidecar returned 200 with a "
                f"{type(payload).__name__}, not an object"
            )
        missing = [key for key in REQUIRED_PAYLOAD_KEYS if payload.get(key) is None]
        if missing:
            raise FetchFailed(
                f"{request.url}: render sidecar returned 200 without "
                f"{', '.join(missing)} — spec 012 §1 requires "
                f"{', '.join(REQUIRED_PAYLOAD_KEYS)}"
            )
        return payload

    @staticmethod
    def _error_of(response: httpx2.Response) -> str:
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text

    async def aclose(self) -> None:
        await self._client.aclose()
