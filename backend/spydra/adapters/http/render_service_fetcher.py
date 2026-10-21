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

# The sidecar's own budget plus room for it to answer. A request that times
# out at the transport before the sidecar can reply 504 would be reported as
# a fetch failure when the sidecar was about to tell us something more useful.
TRANSPORT_HEADROOM_S = 10.0


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

            if response.status_code == 503:
                # Spec 002 §6: our queue, our problem. No penalty.
                raise Backpressure(f"{request.url}: render sidecar has no context available")

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
                timeout=request.timeout_ms / 1000 + TRANSPORT_HEADROOM_S,
            )
        except (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError) as exc:
            # The sidecar is down, not the supplier. Spec 012 §4: a RENDERED
            # domain's rows stay `pending` and the run reports them stalled
            # rather than failed — which is Backpressure's contract, not
            # FetchFailed's. Calling this a fetch failure would charge a
            # healthy domain for our own service being stopped, and three of
            # those is an ADR-0004 pause.
            raise Backpressure(
                f"{request.url}: render sidecar unreachable: {type(exc).__name__}: {exc}"
            ) from exc

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
            "timeout_ms": request.timeout_ms,
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
        payload = response.json()
        return FetchedPage(
            request_url=request.url,
            # The sidecar's `final_url`, not the transport's: the redirect
            # happened in the browser, so httpx2 never saw it and
            # `response.url` is the sidecar's own /render endpoint.
            final_url=str(payload.get("final_url", request.url)),
            # Likewise the status: `response.status_code` is the sidecar
            # saying "I rendered something" (200), while `payload["status"]`
            # is what the SUPPLIER said — which is the one the politeness
            # gate reads.
            http_status=int(payload.get("status", 0)),
            body=str(payload.get("html", "")),
            headers={},
            fetched_at=self._clock.now(),
            elapsed_ms=int((self._clock.monotonic() - started) * 1000),
            fetch_path=self.path,
        )

    @staticmethod
    def _error_of(response: httpx2.Response) -> str:
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text

    async def aclose(self) -> None:
        await self._client.aclose()
