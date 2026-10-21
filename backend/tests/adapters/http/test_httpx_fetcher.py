"""`HttpxFetcher` against the `Fetcher` contract (BUILD_PLAN 1.6).

Written from the port's docstring and `1.6`'s acceptance criteria, not from
the adapter — a test written from the implementation tests what the code
does, and the difference only shows up when the code is wrong (WORKFLOW §3).

`httpx2.MockTransport` with a handler function per scenario (ADR-0028). No
mocking library, no network, no patched clock: the `Clock` is a tiny fake
because `fetched_at` and `elapsed_ms` are *stamped* values, and
`ports/clock.py` is explicit that this port is not a licence to simulate the
politeness guarantee — which is tested elsewhere, against observed time.

**Do not add `__init__.py` to this directory.** `tests/adapters/` has none,
so pytest inserts THIS directory on `sys.path` and imports the module under
its own name. Add one here and pytest inserts `tests/adapters/` instead — at
which point the directory name `http` shadows the standard library's `http`
package and the whole suite dies on `No module named 'http.client'`, raised
from inside httpx2, which reads like a broken dependency rather than a
`sys.path` problem. Measured the hard way while writing this file. The
sibling `postgres/` directory follows the same rule.

**The thing most worth getting right here is what this adapter does NOT do.**
403, 429 and 5xx are successful fetches. An adapter that raised on them, or
that translated a supplier's 503 into `Backpressure`, would be a second
component with an opinion about a block — and ADR-0004 exists because that is
how a temporary rate-limit becomes a permanent ban.
"""

import inspect
import re
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from spydra.adapters.http import HttpxFetcher
from spydra.adapters.http.httpx_fetcher import MAX_REDIRECTS, _ca_bundle
from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchRequest
from spydra.ports.fetcher import Fetcher


def _env_example() -> Path:
    """Locate `.env.example`, which lives at the REPO root, not under backend/.

    The suite runs with `backend/` bind-mounted at `/app`, so walking up from
    this file reaches `/app` and stops — the repo root is a separate mount at
    `/repo` (compose.yaml). Both are tried so the test works in the container
    and from a plain checkout, and a miss is a failure rather than a skip:
    1.6's "done when" names this file specifically.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env.example"
        if candidate.is_file():
            return candidate
    repo = Path("/repo/.env.example")
    if repo.is_file():
        return repo
    pytest.fail(f"could not locate .env.example from {here}")


ENV_EXAMPLE = _env_example()


def env_example_user_agent() -> str:
    """The UA from `.env.example`, read rather than pasted.

    ADR-0004 makes honest identification a property of every request, and
    `1.6`'s "done when" asks for the value from this file specifically. A
    copy in the test drifts from the file silently, and the assertion built
    on it then proves only that the test agrees with itself.
    """
    for line in ENV_EXAMPLE.read_text().splitlines():
        if line.startswith("USER_AGENT="):
            return line.split("=", 1)[1]
    pytest.fail(f"no USER_AGENT in {ENV_EXAMPLE}")


FIXED_NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)


class FakeClock:
    """Wall clock fixed; monotonic advances by a GROWING step.

    The step grows rather than staying constant so that two fetches through
    one adapter produce two different `elapsed_ms` values. A fixed step makes
    every fetch measure the same number, and an adapter returning that number
    as a literal would pass — not a hypothetical: the first version of this
    clock stepped by a constant 0.25 s, and a mutation hard-coding
    `elapsed_ms=250` stayed green against it.

    Whole seconds, so the arithmetic is exact. A 0.1 s step looks tidier and
    is not: accumulating it gives 0.6000000000000001, the subtraction lands
    on 0.39999999999999997, and `int(... * 1000)` truncates to **399**. A
    test whose expected value depends on float accumulation is a test that
    gets "fixed" by loosening the assertion.

    Successive reads are 1, 3, 6, 10 … so one fetch (two reads) measures
    2 s, the next 4 s.
    """

    def __init__(self) -> None:
        self._t = 0.0
        self._calls = 0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return FIXED_NOW

    def monotonic(self) -> float:
        self._calls += 1
        self._t += float(self._calls)
        return self._t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


Handler = Callable[[httpx2.Request], httpx2.Response]


def fetcher(handler: Handler, clock: FakeClock | None = None) -> HttpxFetcher:
    """An adapter whose only difference from production is the transport.

    Built through `HttpxFetcher.build_client` rather than by restating its
    arguments, so every behavioural test below runs against the real
    configuration. Restating them means a client that only *looks* like
    production, and anything added to `build_client` later — connection
    limits, default headers, http2 — would be invisible to all of these.
    """
    return HttpxFetcher(
        clock=clock if clock is not None else FakeClock(),
        client=HttpxFetcher.build_client(transport=httpx2.MockTransport(handler)),
    )


def resolved_ssl_context(client: httpx2.AsyncClient) -> object:
    """The SSL context the client actually ended up with.

    There is no public accessor, and the wiring between `_ca_bundle()` and
    the client is exactly what needs asserting — a test that only checks
    `_ca_bundle()`'s return value leaves `verify=True` passing. The `ignore`
    is here rather than at the two call sites so there is one place to fix
    when an httpx2 upgrade moves it; such an upgrade fails loudly with an
    AttributeError rather than quietly passing.
    """
    return client._transport._pool._ssl_context  # type: ignore[attr-defined]


def request(
    url: str = "https://vantage-abrasives.test/catalog/rfd-115-060",
    *,
    user_agent: str | None = None,
    timeout_ms: int = 20_000,
    headers: Mapping[str, str] | None = None,
) -> FetchRequest:
    """A FetchRequest defaulting to the real user-agent.

    Spelled out rather than `**kwargs` so `mypy --strict` checks every call
    site here against `1.2`'s dataclass — a test helper that launders its
    arguments through `**kwargs` is a test helper that keeps passing after
    the dataclass changes shape.
    """
    return FetchRequest(
        url=url,
        user_agent=user_agent if user_agent is not None else env_example_user_agent(),
        timeout_ms=timeout_ms,
        headers=headers if headers is not None else {},
    )


# ---------------------------------------------------------------------------
# B1 — the happy path
# ---------------------------------------------------------------------------


async def test_a_200_comes_back_as_a_fetched_page() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, html="<h1>Resin Fibre Disc</h1>", headers={"x-origin": "test"})

    f = fetcher(handler)
    try:
        page = await f.fetch(request())
    finally:
        await f.aclose()

    assert page.http_status == 200
    assert "Resin Fibre Disc" in page.body
    assert page.fetch_path is FetchPath.STATIC
    assert page.headers["x-origin"] == "test"
    # From the INJECTED clock, not `datetime.now()`. Asserting only that it
    # is timezone-aware passes against an adapter that reads the wall clock
    # directly, and the injection is what lets 1.9's backoff-decay and
    # lease-expiry tests drive observation timestamps at all.
    assert page.fetched_at == FIXED_NOW
    # Persisted as TIMESTAMPTZ (spec 001 §1), so a naive datetime here would
    # be an hour of silent drift rather than an error.
    assert page.fetched_at.tzinfo is not None
    # Two monotonic reads at 1 s and 3 s on the growing clock.
    assert page.elapsed_ms == 2000


async def test_elapsed_ms_is_measured_per_fetch_not_a_constant() -> None:
    """Two fetches through one adapter, with the clock's step growing, so an
    adapter returning a literal cannot pass. The previous version of this
    suite used a constant-step clock, and `elapsed_ms = 250` survived it."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, html="ok")

    f = fetcher(handler)
    try:
        first = await f.fetch(request())
        second = await f.fetch(request())
    finally:
        await f.aclose()

    assert first.elapsed_ms == 2000
    assert second.elapsed_ms == 4000
    assert first.elapsed_ms != second.elapsed_ms


# ---------------------------------------------------------------------------
# B2 — the status table. The criterion this adapter exists to respect.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 301, 400, 403, 404, 429, 500, 503])
async def test_every_http_status_is_a_successful_fetch(status: int) -> None:
    """ADR-0004 and the port's docstring: an HTTP error status is a *successful*
    fetch. Deciding what a 403 or a 429 means is the politeness gate's job
    (1.9), and an adapter with its own opinion is the second component with
    one — which is how a retry loop runs against a site that already refused."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        # No Location header, so a 3xx terminates here rather than redirecting.
        return httpx2.Response(status, text="body")

    f = fetcher(handler)
    try:
        page = await f.fetch(request())
    finally:
        await f.aclose()

    assert page.http_status == status


async def test_a_suppliers_503_is_a_status_and_never_backpressure() -> None:
    """The one place the two adapters genuinely diverge, and it is easy to get
    backwards. ADR-0004 sends a *site's* 503 to backoff with
    `consecutive_failures` incremented; spec 002 §6 sends the *render
    sidecar's* 503 to backpressure with no penalty. There is no sidecar on
    this path, so nothing seen here is ever the second kind — and if this
    adapter raised `Backpressure`, a supplier could suppress its own failure
    count by answering 503."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text="slow down")

    f = fetcher(handler)
    try:
        page = await f.fetch(request())
    except Backpressure:  # pragma: no cover - the failure this test exists for
        pytest.fail("HttpxFetcher raised Backpressure for a supplier's 503")
    finally:
        await f.aclose()

    assert page.http_status == 503
    assert page.body == "slow down"


# ---------------------------------------------------------------------------
# B3, B4 — no response at all
# ---------------------------------------------------------------------------


def raising(exc_type: type[httpx2.RequestError]) -> Handler:
    """A MockTransport handler that fails instead of responding.

    `MockTransport` calls the handler and expects a `Response`; raising from
    inside it is how a transport-level failure is simulated without a socket.
    """

    def handler(req: httpx2.Request) -> httpx2.Response:
        raise exc_type("simulated transport failure", request=req)

    return handler


@pytest.mark.parametrize(
    "exc_type",
    [
        pytest.param(httpx2.ReadTimeout, id="read-timeout"),
        pytest.param(httpx2.ConnectTimeout, id="connect-timeout"),
        pytest.param(httpx2.ConnectError, id="connect-error"),
        pytest.param(httpx2.RemoteProtocolError, id="remote-protocol-error"),
    ],
)
async def test_a_request_with_no_response_raises_fetch_failed(
    exc_type: type[httpx2.RequestError],
) -> None:
    """The scheduler reads the port's vocabulary, never the client's. A bare
    `httpx2.TimeoutException` reaching 1.9 would be an exception it has no
    branch for, and the swap to 1.7's adapter would not be transparent."""
    f = fetcher(raising(exc_type))
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()


async def test_an_endless_redirect_chain_raises_fetch_failed() -> None:
    """Exhausting `max_redirects` produces no response, so it is a failure
    rather than a status — and it must not surface as httpx2's own
    `TooManyRedirects`."""

    def handler(req: httpx2.Request) -> httpx2.Response:
        n = int(req.url.params.get("n", "0"))
        return httpx2.Response(302, headers={"location": f"/loop?n={n + 1}"})

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request(url="https://northfield.test/loop?n=0"))
    finally:
        await f.aclose()


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://[::1", id="unterminated-ipv6"),
        pytest.param("http://\uffff.test/", id="host-that-cannot-be-idna-encoded"),
    ],
)
async def test_a_malformed_url_raises_fetch_failed_not_a_client_exception(url: str) -> None:
    """`httpx2.InvalidURL` does NOT inherit from `httpx2.HTTPError` — measured
    against 2.13.1, it comes straight off `Exception`, which is why the
    adapter catches it by name. A junk URL out of the frontier would otherwise
    escape the port's vocabulary and take the worker loop down with an
    exception the scheduler has no branch for.

    Both inputs were chosen by measurement, and most "obviously invalid" URLs
    are not: `http://`, `not-a-url`, `ftp://h.test/x` and `http://%zz.test/`
    all reach the transport without raising. These two are the ones that
    actually exercise the path.
    """

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("the request should never have been attempted")

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request(url=url))
    finally:
        await f.aclose()


@pytest.mark.parametrize(
    ("user_agent", "headers"),
    [
        pytest.param(
            "Müller-Abrasives Crawler/1.0 (+https://m.test)",
            None,
            id="in-the-user-agent",
        ),
        pytest.param(None, {"x-note": "café"}, id="in-a-caller-header"),
    ],
)
async def test_a_non_ascii_header_value_raises_fetch_failed(
    user_agent: str | None,
    headers: dict[str, str] | None,
) -> None:
    """httpx2 encodes header values as ASCII and raises a **builtin**
    `UnicodeEncodeError` before any transport is touched — measured on
    2.13.1, and it is not an `httpx2.HTTPError`.

    This matters because of where the value comes from. `domains.user_agent`
    is TEXT and the operator edits it (spec 001 §1, spec 005), so an honest
    `Müller-Abrasives Crawler/1.0 (+https://…)` — exactly the sort of
    identification ADR-0004 asks for — would otherwise raise out of `fetch()`
    on every claim for that domain. The worker loop has no branch for a
    builtin, so a typo in one text box stalls a domain until its lease
    expires instead of failing a single page.
    """

    def handler(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        pytest.fail("the request should never have reached the transport")

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request(user_agent=user_agent, headers=headers))
    finally:
        await f.aclose()


# ---------------------------------------------------------------------------
# B5 — redirects are recorded, not decided about
# ---------------------------------------------------------------------------


async def test_a_redirect_is_followed_and_both_urls_are_kept() -> None:
    """`FetchedPage.redirected` compares the two, so a test that only checked
    `final_url` would pass against an adapter that overwrote `request_url`."""

    def handler(req: httpx2.Request) -> httpx2.Response:
        if req.url.path == "/old":
            return httpx2.Response(301, headers={"location": "/new"})
        return httpx2.Response(200, html="<h1>moved</h1>")

    f = fetcher(handler)
    try:
        page = await f.fetch(request(url="https://northfield.test/old"))
    finally:
        await f.aclose()

    assert page.http_status == 200
    assert page.request_url == "https://northfield.test/old"
    assert page.final_url == "https://northfield.test/new"
    assert page.redirected is True


async def test_a_response_with_no_redirect_is_not_marked_redirected() -> None:
    """The other half of B5. Without it, an adapter that always reported a
    redirect would pass the test above."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, html="<h1>here</h1>")

    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    f = fetcher(handler)
    try:
        page = await f.fetch(request(url=url))
    finally:
        await f.aclose()

    assert page.final_url == url
    assert page.redirected is False


# ---------------------------------------------------------------------------
# B6, B7 — honest identification (ADR-0004)
# ---------------------------------------------------------------------------


async def test_the_user_agent_from_env_example_is_on_the_wire() -> None:
    """ADR-0004: the crawler identifies itself honestly, with contact
    information, and does not impersonate a browser. Asserted on the OUTGOING
    request, because that is the only place it matters."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, html="ok")

    expected = env_example_user_agent()
    f = fetcher(handler)
    try:
        await f.fetch(request())
    finally:
        await f.aclose()

    assert seen[0].headers.get_list("user-agent") == [expected]
    # The ADR's two substantive requirements, not just "some string was set":
    # contact information present, and no browser impersonation.
    assert re.search(r"https?://|@", expected), "the UA carries no contact route (ADR-0004)"
    for browser in ("Mozilla", "Chrome", "Safari", "AppleWebKit"):
        assert browser not in expected, f"the UA impersonates a browser ({browser}) — ADR-0004"


async def test_caller_headers_reach_the_wire() -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, html="ok")

    f = fetcher(handler)
    try:
        await f.fetch(request(headers={"accept-language": "de-DE"}))
    finally:
        await f.aclose()

    assert seen[0].headers["accept-language"] == "de-DE"


async def test_a_caller_cannot_override_the_user_agent_through_headers() -> None:
    """`FetchRequest.user_agent` is required so that no path can send httpx's
    default (the field's own docstring). A caller must not be able to defeat
    it through `headers` either.

    Odd casing on purpose, and the assertion is on `get_list`, not `get`.
    Measured against httpx2 2.13.1: a mapping holding both `User-Agent` and
    `user-agent` emits TWO header lines and `get()` returns them joined as
    `"caller, ours"` — so a `get()`-based assertion with `in` would pass
    while the request went out misidentified, which is the one thing
    ADR-0004 asks this field to prevent."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, html="ok")

    expected = env_example_user_agent()
    f = fetcher(handler)
    try:
        await f.fetch(request(headers={"User-Agent": "Mozilla/5.0 (definitely a browser)"}))
    finally:
        await f.aclose()

    assert seen[0].headers.get_list("user-agent") == [expected]


# ---------------------------------------------------------------------------
# B8, B9 — the rest of the contract
# ---------------------------------------------------------------------------


async def test_the_per_request_timeout_is_what_is_used() -> None:
    """`FetchRequest.timeout_ms` is per request because a domain can carry its
    own (spec 001 §1). A module-level default would ignore it silently."""
    # httpx2 resolves the timeout and hands it to the transport through the
    # request's extensions, as a mapping of seconds per phase.
    seen: list[Mapping[str, float | None]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req.extensions["timeout"])
        return httpx2.Response(200, html="ok")

    f = fetcher(handler)
    try:
        await f.fetch(request(timeout_ms=3500))
    finally:
        await f.aclose()

    # All four phases, not just `read`. Asserting one of them leaves three
    # unasserted, and a mutation setting `connect=5.0` passed that way.
    resolved = seen[0]
    assert resolved["connect"] == pytest.approx(3.5)
    assert resolved["read"] == pytest.approx(3.5)
    assert resolved["write"] == pytest.approx(3.5)
    # `pool` is deliberately unbounded: it is how long we wait for one of OUR
    # OWN connections, and a PoolTimeout is an HTTPError, so a bounded pool
    # wait would become FetchFailed -> `fetch_error` -> a rising
    # `consecutive_failures` against a supplier that answered fine. Spec 002
    # §6 makes that argument about a busy sidecar; a busy pool of ours is the
    # same mistake.
    assert resolved["pool"] is None


async def test_the_default_client_ignores_proxy_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every other test here injects its own client, so the production client
    this adapter builds for itself would otherwise be asserted by nothing.

    ADR-0004 puts proxy rotation explicitly out of scope, and httpx reads
    `HTTP_PROXY` / `HTTPS_PROXY` from the environment unless told not to. An
    ambient variable quietly changing which IP a supplier sees — and so
    whether we get blocked — is the opposite of the honest identification
    that ADR asks for.

    Asserted on the client's resolved proxy mounts rather than on the
    `trust_env` flag: the flag is what we passed in, the mounts are what it
    did. Measured against httpx2 2.13.1 — with these two variables set, a
    `trust_env=True` client resolves two proxy mounts and a `trust_env=False`
    client resolves none.
    """
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")

    client = HttpxFetcher.build_client()
    try:
        assert client.follow_redirects is True
        # The VALUE, not `== MAX_REDIRECTS`, which compares the constant to
        # itself and let a change from 10 to 2 through with all tests green.
        # Lowering it makes an ordinary canonicalisation chain
        # (http -> https -> www -> trailing slash) exhaust the budget, which
        # this adapter reports as FetchFailed and 1.9 charges to the domain.
        assert client.max_redirects == 10
        assert MAX_REDIRECTS == 10
        # The private attribute is the point of this test: `trust_env` is
        # what we passed in, the resolved mounts are what it did. No `noqa`
        # code — `SLF` is not in pyproject's ruff `select`, so one here
        # suppresses nothing and becomes an RUF100 failure the day it is.
        assert list(client._mounts) == [], (
            "the crawler picked up a proxy from the environment (ADR-0004)"
        )
    finally:
        await client.aclose()


async def test_the_default_client_still_honours_the_certificate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`trust_env=False` is the only thing that stops proxy inheritance —
    measured on httpx2 2.13.1, `mounts={}` and `proxy=None` are both ignored
    while it is on. But httpx2 gates `SSL_CERT_FILE` and `SSL_CERT_DIR` on
    the same flag, so turning proxies off silently takes the operator's
    private CA with it.

    The failure that would cause is the quiet kind: an operator behind a
    TLS-inspecting proxy gets ConnectError -> FetchFailed -> a rising
    `consecutive_failures` -> an eventually paused domain, with nothing
    anywhere mentioning a certificate. So the adapter re-honours that half
    itself, and this is the test that says so.
    """
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")

    assert isinstance(_ca_bundle(), ssl.SSLContext)

    # ...and the client must actually USE it. Asserting only that
    # `_ca_bundle()` returns a context leaves the wiring unguarded: a
    # mutation replacing `verify=_ca_bundle()` with `verify=True` kept all 30
    # tests green, because nothing looked at the client.
    #
    # The discriminator is the TYPE of the resolved context, measured on
    # httpx2 2.13.1: `verify=True` resolves to `truststore._api.SSLContext`
    # and an explicit context stays exactly `ssl.SSLContext`. `isinstance`
    # cannot tell them apart — truststore's subclasses `ssl.SSLContext` — so
    # this is an exact type check.
    #
    # The private path is reached deliberately: the wiring between
    # `_ca_bundle()` and the client is the subject, and there is no public
    # accessor. An httpx2 upgrade that moves it fails loudly with an
    # AttributeError rather than quietly passing.
    client = HttpxFetcher.build_client()
    try:
        resolved = resolved_ssl_context(client)
        assert type(resolved) is ssl.SSLContext, (
            f"the operator's SSL_CERT_FILE never reached the client "
            f"(resolved context is {type(resolved).__module__}.{type(resolved).__name__})"
        )
    finally:
        await client.aclose()

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert _ca_bundle() is True, "no certificate environment should mean httpx2's defaults"

    default = HttpxFetcher.build_client()
    try:
        assert type(resolved_ssl_context(default)) is not ssl.SSLContext, (
            "with no certificate environment the client should use httpx2's own default"
        )
    finally:
        await default.aclose()


async def test_aclose_closes_the_pool() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, html="ok")

    f = fetcher(handler)
    await f.fetch(request())
    await f.aclose()

    with pytest.raises(RuntimeError):
        await f.fetch(request())


def test_the_adapter_satisfies_the_fetcher_protocol() -> None:
    """Structural, in both directions: a drift in the adapter OR in the port
    is caught here rather than at the first call site in 1.13.

    Checked by `mypy --strict` through the annotation below rather than with
    `isinstance`. No port in `spydra/ports/` is `@runtime_checkable`, and
    adding that decorator to satisfy a test would be the test changing the
    port — which is the thing 1.2 wrote the port early to prevent. It would
    also be the weaker check: `runtime_checkable` verifies that the attribute
    names exist and says nothing about their signatures, so it passes against
    a `fetch` taking the wrong arguments.
    """
    adapter: Fetcher = HttpxFetcher(clock=FakeClock())
    assert adapter.path is FetchPath.STATIC

    sig = inspect.signature(adapter.fetch)
    assert list(sig.parameters) == ["request"]
    assert inspect.iscoroutinefunction(adapter.fetch)
    assert inspect.iscoroutinefunction(adapter.aclose)
