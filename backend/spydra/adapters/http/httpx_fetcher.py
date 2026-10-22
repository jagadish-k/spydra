"""The static fetch path — `Fetcher` over httpx2 (BUILD_PLAN 1.6).

**This adapter decides nothing.** It turns one URL into one `FetchedPage`,
or reports that no response arrived. What a 403 or a 429 *means* belongs to
the politeness gate (spec 002 §4, ADR-0004), and an adapter that formed an
opinion here would be the second component with one — which is how a retry
loop ends up running against a site that has already decided to refuse us.

So the status table is deliberately flat: every HTTP status, error statuses
included, is a **successful fetch** carrying that status. The only failure
this raises is "there was no response at all".

It also never raises `Backpressure`. That is easy to get backwards, because
ADR-0004 and spec 002 §6 both have an opinion about 503:

  - a **supplier's** 503 is a status, and the gate backs off and counts it
    against the domain (ADR-0004);
  - the **render sidecar's** 503 is backpressure, and the row returns to
    `pending` with no penalty (spec 002 §6).

There is no sidecar on this path, so no 503 seen here is ever the second
kind. `RenderServiceFetcher` (1.7) is where `Backpressure` comes from.
"""

import os
import ssl
from collections.abc import Mapping

import httpx2

from spydra.domain.enums import FetchPath
from spydra.domain.errors import FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.ports.clock import Clock

# Enough to follow a canonicalisation chain (http→https→trailing slash→www)
# without following a loop for long. Exhausting it yields no response, so it
# is a FetchFailed rather than a status — which means lowering this makes a
# healthy supplier look broken: 1.9 records `fetch_error` and charges the
# domain. The test asserts the VALUE, not this symbol; comparing the constant
# to itself would let any change through.
MAX_REDIRECTS = 10


def _ca_bundle() -> ssl.SSLContext | bool:
    """Honour SSL_CERT_FILE / SSL_CERT_DIR even though `trust_env` is off.

    `trust_env=False` is what stops proxy inheritance (ADR-0004), and httpx2
    gates the certificate environment on the same flag — so turning proxies
    off silently takes the operator's private CA with it. This puts just that
    half back.
    """
    cafile = os.environ.get("SSL_CERT_FILE")
    capath = os.environ.get("SSL_CERT_DIR")
    if not cafile and not capath:
        return True
    return ssl.create_default_context(cafile=cafile or None, capath=capath or None)


class HttpxFetcher:
    """`Fetcher` over one pooled httpx2 client.

    One client for the adapter's lifetime, not one per fetch: connection
    reuse is most of the reason a crawl is cheap, and a client per request
    also re-does TLS against every host on every page.

    The `Clock` is injected rather than read from `time`, because
    `fetched_at` and `elapsed_ms` are persisted and the port for this already
    exists (1.2, ADR-0008). Note this is *stamping*, not simulating:
    ADR-0028's suite and TESTING.md §2's politeness tests still assert on
    observed time, and `ports/clock.py` says plainly that this port is not a
    licence to fake the guarantee.
    """

    path = FetchPath.STATIC

    def __init__(self, clock: Clock, client: httpx2.AsyncClient | None = None) -> None:
        self._clock = clock
        self._client = client if client is not None else self.build_client()

    @staticmethod
    def build_client(transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
        """The production client. `transport` is the test seam.

        Public, and taking a transport, so the suite exercises **this**
        configuration rather than a hand-rolled copy of it. A test that
        restates `follow_redirects` and `max_redirects` itself is a test that
        cannot see anything later added here.
        """
        return httpx2.AsyncClient(
            transport=transport,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            # httpx reads HTTP_PROXY/HTTPS_PROXY from the environment when
            # this is left on. ADR-0004 puts proxy rotation out of scope, and
            # an ambient variable quietly changing which IP a supplier sees —
            # and so whether we get blocked — is the opposite of the honest
            # identification that ADR asks for.
            #
            # Measured on httpx2 2.13.1: this is the ONLY way to stop proxy
            # inheritance. `mounts={}` and `proxy=None` are both ignored
            # while `trust_env` is on — the environment proxies are still
            # resolved into two mounts — so the narrower-looking fix does not
            # work. The cost is that `trust_env` also gates SSL_CERT_FILE and
            # SSL_CERT_DIR, which is why those are re-honoured just below:
            # without that, an operator behind a TLS-inspecting proxy or with
            # a private CA gets ConnectError -> FetchFailed -> a rising
            # failure count and eventually a paused domain, with nothing
            # anywhere saying "certificate".
            trust_env=False,
            verify=_ca_bundle(),
        )

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        """Retrieve one URL. See the module docstring for what this does not do.

        Raises:
            FetchFailed: no response arrived — DNS, refused, timeout, a
                redirect chain that never terminated, or a request that could
                not be built at all.
        """
        started = self._clock.monotonic()
        try:
            response = await self._client.get(
                request.url,
                headers=self._headers(request),
                # `pool=None` so OUR OWN saturation is never charged to the
                # supplier. A scalar timeout sets all four phases, pool wait
                # included, and a PoolTimeout is an HTTPError — so it would
                # become FetchFailed, then `fetch_error`, then a rising
                # `consecutive_failures` against a domain that answered
                # perfectly well. Spec 002 §6 makes exactly this argument
                # about a busy sidecar; a busy connection pool of ours is the
                # same mistake wearing different clothes.
                timeout=httpx2.Timeout(request.timeout_ms / 1000, pool=None),
            )
        except (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError) as exc:
            # Everything httpx2 raises for a request that produced no usable
            # response is one failure as far as the port is concerned:
            # TimeoutException, ConnectError, TooManyRedirects,
            # UnsupportedProtocol and the rest are all "nothing came back".
            # Translating here is the point of the port — the scheduler reads
            # the domain's vocabulary, never the client's, which is what lets
            # 1.7 swap in without touching a single scheduler branch.
            #
            # Two of the three are not httpx2 exceptions at all, and both
            # were found by measuring rather than by reading:
            #
            # `InvalidURL` does NOT inherit from `HTTPError` — it comes
            # straight off `Exception`. A junk URL out of the frontier would
            # otherwise escape this translation and take the worker loop down
            # with an exception the scheduler has no branch for.
            #
            # `UnicodeError` covers the `UnicodeEncodeError` that httpx2
            # raises when a header value is not ASCII-encodable, before any
            # transport is touched. `domains.user_agent` is TEXT and the
            # operator edits it (spec 001 §1, spec 005), so an honest
            # `Müller-Abrasives Crawler/1.0 (+https://…)` — precisely the
            # kind of value ADR-0004 asks for — would otherwise raise a
            # builtin out of `fetch()` on every claim for that domain and
            # stall it until the lease expired. A typo in one text box should
            # fail one page, not a domain.
            raise FetchFailed(f"{request.url}: {type(exc).__name__}: {exc}") from exc

        elapsed_ms = int((self._clock.monotonic() - started) * 1000)
        return FetchedPage(
            request_url=request.url,
            # Where it ended, which is what makes `redirected` mean anything.
            final_url=str(response.url),
            http_status=response.status_code,
            body=response.text,
            headers=dict(response.headers),
            fetched_at=self._clock.now(),
            elapsed_ms=elapsed_ms,
            fetch_path=self.path,
        )

    @staticmethod
    def _headers(request: FetchRequest) -> Mapping[str, str]:
        """Per-request headers, with any caller-supplied user-agent REMOVED.

        `FetchRequest.user_agent` is required so that no code path can send
        httpx's default (ADR-0004), so a caller passing `user-agent` in
        `headers` must not be able to defeat it: honest identification is a
        property of every request, not a default a caller can opt out of.

        The drop has to be case-insensitive, and `{**headers, "user-agent":
        ua}` is not enough. Measured against httpx2 2.13.1: a mapping holding
        both `User-Agent` and `user-agent` produces TWO header lines, and
        `headers.get("user-agent")` then returns `"caller, ours"` — the
        caller's value first. HTTP permits the repetition, so nothing raises;
        the request simply goes out misidentified, which is the one thing
        ADR-0004 asks this field to prevent.
        """
        headers = {k: v for k, v in request.headers.items() if k.lower() != "user-agent"}
        headers["user-agent"] = request.user_agent
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()
