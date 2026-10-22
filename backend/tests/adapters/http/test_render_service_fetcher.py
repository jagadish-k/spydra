"""`RenderServiceFetcher` against the `Fetcher` contract (BUILD_PLAN 1.7).

Written from spec 012 §1's status table and §4's behaviour, not from the
adapter. `httpx2.MockTransport` handlers only (ADR-0028) — the Python suite
never starts Chromium (TESTING.md §1); the sidecar has its own suite that
drives a real browser, which is BUILD_PLAN 1.5.

**No `__init__.py` in this directory** — see the note in
`test_httpx_fetcher.py`; a package here puts `tests/adapters/` on `sys.path`
and the directory name `http` shadows the stdlib's.

The criterion worth the most attention is the difference between two
failures that look alike from the outside:

  - **503** — our own sidecar is full. Requeue, no penalty (spec 002 §6).
  - **502 / 422** — nothing was rendered and a retry would not change that.

Getting those the wrong way round means either a healthy domain walking
toward an ADR-0004 pause because a browser of ours was busy, or a genuinely
broken page quietly retrying forever.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import httpx2
import pytest

from spydra.adapters.http import RenderServiceFetcher
from spydra.adapters.http.render_service_fetcher import (
    LEASE_BUDGET_S,
    RENDER_TIMEOUT_RETRIES,
    SIDECAR_MAX_TIMEOUT_MS,
    TRANSPORT_HEADROOM_S,
)
from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchRequest

Handler = Callable[[httpx2.Request], httpx2.Response]

SIDECAR = "http://host.docker.internal:3001"
PAGE_URL = "https://mertens.test/katalog/stirnlochschluessel-30-80"
RENDERED_HTML = '<html><div class="produkt__preis">24,90 EUR</div></html>'
FIXED_NOW = datetime(2026, 10, 21, 11, 15, tzinfo=UTC)


class FakeClock:
    """Whole-second growing steps, so `elapsed_ms` is exact and not constant.
    Same reasoning as `test_httpx_fetcher.py`'s — a fixed step lets a
    hard-coded `elapsed_ms` pass."""

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


def fetcher(handler: Handler) -> RenderServiceFetcher:
    """Built through the production `build_client`, so the suite exercises
    that configuration rather than a copy of it."""
    return RenderServiceFetcher(
        base_url=SIDECAR,
        clock=FakeClock(),
        client=RenderServiceFetcher.build_client(transport=httpx2.MockTransport(handler)),
    )


USER_AGENT = "MySampleScraper/1.0 (+https://jagadishk.work)"


def request(
    url: str = PAGE_URL,
    *,
    user_agent: str = USER_AGENT,
    timeout_ms: int = 20_000,
    headers: Mapping[str, str] | None = None,
    wait_for_selector: str | None = None,
) -> FetchRequest:
    """Spelled out rather than `**kwargs`.

    The first version laundered them through `**kw` and a
    `# type: ignore[arg-type]` whose comment said "kwargs are checked by the
    dataclass" — which is false: a plain dataclass checks nothing at runtime,
    so after the ignore nothing checked them at all. The sibling
    `test_httpx_fetcher.py` already used this shape.
    """
    return FetchRequest(
        url=url,
        user_agent=user_agent,
        timeout_ms=timeout_ms,
        headers=headers if headers is not None else {},
        wait_for_selector=wait_for_selector,
    )


def rendered(sidecar_status: int = 200, **overrides: object) -> httpx2.Response:
    """A sidecar /render response.

    `sidecar_status` is the SIDECAR's HTTP status; `status` inside the payload
    is the SUPPLIER's. Naming them apart matters — they are the pair this
    adapter is easiest to get wrong about, and a shared name here collided
    on the very first call.
    """
    payload: dict[str, object] = {
        "html": RENDERED_HTML,
        "status": 200,
        "final_url": PAGE_URL,
        "timing_ms": {"navigate": 1840, "settle": 370, "total": 2210},
        "console_errors": 0,
    }
    payload.update(overrides)
    return httpx2.Response(sidecar_status, json=payload)


# ---------------------------------------------------------------------------
# C1 — the happy path
# ---------------------------------------------------------------------------


async def test_a_rendered_page_carries_the_sidecars_url_and_status() -> None:
    """The two values that are easy to take from the wrong place.

    `response.status_code` is the sidecar saying "I rendered something"; the
    SUPPLIER's status is in the payload, and that is the one the politeness
    gate reads. Likewise the redirect happened inside the browser, so httpx2
    never saw it and `response.url` is the sidecar's own /render endpoint.
    """
    final = "https://mertens.test/katalog/stirnlochschluessel-30-80/"

    def handler(_: httpx2.Request) -> httpx2.Response:
        return rendered(200, status=404, final_url=final)

    f = fetcher(handler)
    try:
        page = await f.fetch(request())
    finally:
        await f.aclose()

    assert page.fetch_path is FetchPath.RENDERED
    assert page.body == RENDERED_HTML
    assert page.http_status == 404, "the supplier's status, not the sidecar's 200"
    assert page.final_url == final, "the browser's final URL, not the /render endpoint"
    assert page.request_url == PAGE_URL
    assert page.fetched_at == FIXED_NOW
    assert page.elapsed_ms == 2000
    assert page.fell_back_from is None


# ---------------------------------------------------------------------------
# C2, C5, C6, C7 — the status table, and the one code that is not a failure
# ---------------------------------------------------------------------------


async def test_a_503_is_backpressure_and_not_a_fetch_failure() -> None:
    """Spec 002 §6. The sidecar's queue is full: the row returns to `pending`
    with no `consecutive_failures`, no backoff and no attempt charged.

    If this were `FetchFailed`, three busy moments would walk a healthy
    supplier toward an ADR-0004 pause — a domain paused because a browser of
    ours was busy, which is precisely what that spec section forbids."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, json={"error": "no context available within 5000ms"})

    f = fetcher(handler)
    try:
        with pytest.raises(Backpressure):
            await f.fetch(request())
    finally:
        await f.aclose()


@pytest.mark.parametrize("status", [502, 422, 404])
async def test_other_sidecar_errors_are_fetch_failures(status: int) -> None:
    """502 is a navigation failure, 422 is a bug in our own request body, and
    404 means a misconfigured base URL. None improves on a retry.

    **500 is deliberately not in this list.** It was, and that was a defect:
    `render/src/index.js` answers 500 when the browser will not launch or a
    context cannot be created, which is the sidecar being unavailable — see
    the backpressure test below."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": "nope"})

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()


@pytest.mark.parametrize("status", [502, 422])
async def test_a_non_timeout_error_is_not_retried(status: int) -> None:
    """Only 504 gets the retry. Retrying a malformed request produces the
    same malformed request, and retrying a DNS failure is pointless —
    asserted on the number of requests the sidecar actually saw, because
    "not retried" is otherwise invisible."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(status, json={"error": "nope"})

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()

    assert len(seen) == 1


async def test_an_unreachable_sidecar_is_backpressure_so_rendered_stalls_honestly() -> None:
    """Spec 012 §4: with `render` stopped, a RENDERED domain's rows "leave
    their queue rows `pending` and the run reports them as stalled, not
    failed". That is `Backpressure`'s contract, not `FetchFailed`'s.

    Read the other way, stopping our own sidecar for maintenance would charge
    every rendered domain three failures and pause them (ADR-0004)."""

    def handler(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=req)

    f = fetcher(handler)
    try:
        with pytest.raises(Backpressure):
            await f.fetch(request())
    finally:
        await f.aclose()


# ---------------------------------------------------------------------------
# C3, C4 — exactly one retry, and only for 504
# ---------------------------------------------------------------------------


async def test_a_504_is_retried_exactly_once_then_fails() -> None:
    """Spec 012 §1. "Once" asserted on the request count: a test that only
    checked the exception passes against zero retries and against ten."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(504, json={"error": "render timed out"})

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()

    assert len(seen) == 2, f"expected one retry, the sidecar saw {len(seen)} requests"


async def test_a_504_that_succeeds_on_the_retry_returns_the_page() -> None:
    """The retry has to be able to win, or it is a delay with extra steps."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        if len(seen) == 1:
            return httpx2.Response(504, json={"error": "render timed out"})
        return rendered()

    f = fetcher(handler)
    try:
        page = await f.fetch(request())
    finally:
        await f.aclose()

    assert len(seen) == 2
    assert page.body == RENDERED_HTML


# ---------------------------------------------------------------------------
# C8 — the request body spec 012 §1 documents
# ---------------------------------------------------------------------------


async def test_the_request_body_matches_the_sidecars_contract() -> None:
    import json

    bodies: list[dict[str, object]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        return rendered()

    f = fetcher(handler)
    try:
        await f.fetch(
            request(timeout_ms=15_000, headers={"accept-language": "de-DE"}),
        )
    finally:
        await f.aclose()

    body = bodies[0]
    assert body["url"] == PAGE_URL
    assert body["wait_until"] == "networkidle"
    assert body["timeout_ms"] == 15_000
    # Sent explicitly rather than left to the sidecar's own default, so the
    # two cannot drift apart silently (spec 012 §2).
    assert body["block_resources"] == ["image", "font", "media"]
    # ADR-0004 applies to the rendered path too: the browser identifies
    # itself as us, and does not impersonate Chrome.
    assert body["user_agent"] == "MySampleScraper/1.0 (+https://jagadishk.work)"
    assert body["extra_headers"] == {"accept-language": "de-DE"}
    # Omitted, not null: the sidecar validates it as a non-empty string and
    # answers 422 otherwise, which this adapter would report as its own bug.
    assert "wait_for_selector" not in body


async def test_wait_for_selector_is_sent_when_the_request_has_one() -> None:
    import json

    bodies: list[dict[str, object]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        return rendered()

    f = fetcher(handler)
    try:
        await f.fetch(request(wait_for_selector=".produkt__preis"))
    finally:
        await f.aclose()

    assert bodies[0]["wait_for_selector"] == ".produkt__preis"


def test_the_adapter_satisfies_the_fetcher_protocol() -> None:
    """Checked by `mypy --strict` through the annotation, as in 1.6 — no port
    in `spydra/ports/` is `@runtime_checkable`, and adding that to satisfy a
    test would be the test changing the port."""
    from spydra.ports.fetcher import Fetcher

    adapter: Fetcher = RenderServiceFetcher(base_url=SIDECAR, clock=FakeClock())
    assert adapter.path is FetchPath.RENDERED


# ---------------------------------------------------------------------------
# Guards added after review. Each of these had a surviving mutation.
# ---------------------------------------------------------------------------


async def test_a_sidecar_500_is_backpressure_because_it_means_it_cannot_serve() -> None:
    """`render/src/index.js` answers 500 when the browser will not launch or a
    context cannot be created — a `/dev/shm`-starved Chromium that fails to
    relaunch after a recycle answers 500 to **every** request.

    That is the sidecar being unavailable, which spec 012 §4 and ADR-0016
    answer with "rows stay `pending`, reported stalled, **not** failed". As
    `FetchFailed` it was charged to the supplier: RENDERED pages retried
    three times and marked failed, and — worse — `AutoFetcher` falls back on
    `Backpressure` only, so AUTO domains would not have fallen back at all
    for the one status the sidecar emits when its browser is broken.
    """

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": "browser unavailable: launch failed"})

    f = fetcher(handler)
    try:
        with pytest.raises(Backpressure):
            await f.fetch(request())
    finally:
        await f.aclose()


async def test_a_malformed_base_url_fails_rather_than_requeueing_for_ever() -> None:
    """A permanent misconfiguration of ours must not look transient.

    As `Backpressure` — which is where `InvalidURL` landed, copied from the
    static adapter's except tuple — a typo in `RENDER_BASE_URL` requeues
    every rendered row for ever: no `consecutive_failures`, no backoff, no
    error and no run completion. It belongs with 422.
    """
    f = RenderServiceFetcher(
        base_url="http://[::1",
        clock=FakeClock(),
        client=RenderServiceFetcher.build_client(
            transport=httpx2.MockTransport(lambda _: rendered())
        ),
    )
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()


@pytest.mark.parametrize(
    ("label", "response"),
    [
        pytest.param("not JSON", httpx2.Response(200, text="<html>oops</html>"), id="not-json"),
        pytest.param("a list", httpx2.Response(200, json=[1, 2]), id="json-list"),
        pytest.param("empty object", httpx2.Response(200, json={}), id="empty-object"),
        pytest.param(
            "no html",
            httpx2.Response(200, json={"status": 200, "final_url": PAGE_URL}),
            id="missing-html",
        ),
        pytest.param(
            "null status",
            httpx2.Response(200, json={"html": "<p/>", "status": None, "final_url": PAGE_URL}),
            id="null-status",
        ),
    ],
)
async def test_a_200_that_is_not_a_rendered_page_fails_instead_of_inventing_one(
    label: str, response: httpx2.Response
) -> None:
    """The defect this replaced was `payload.get("status", 0)` and
    `payload.get("html", "")`, which turn a sidecar regression into a page
    that looks real: empty body, status 0.

    The consequence is not cosmetic. The extraction chain scores
    `empty_extraction` on an empty body, and `1.11` moves a domain to
    **BROKEN** past 20% — so a payload bug on *our* side marks healthy
    supplier domains broken. And status 0 appears in no row of spec 002 §4's
    table, so the politeness gate has no branch for it and
    `consecutive_failures` never resets.

    Two of these inputs also escaped the port's vocabulary entirely before
    the fix: a non-JSON body raised `JSONDecodeError` and a JSON list raised
    `AttributeError`, neither of which `ports/fetcher.py` declares. Through
    `1.13`'s TaskGroup that leaves `in_flight` incremented and the row
    leased, so one bad response stalls the domain until the 120-second sweep.
    """

    def handler(_: httpx2.Request) -> httpx2.Response:
        return response

    f = fetcher(handler)
    try:
        with pytest.raises(FetchFailed):
            await f.fetch(request())
    finally:
        await f.aclose()
    assert label


async def test_the_request_goes_to_the_render_endpoint() -> None:
    """Nothing pinned the path or the `rstrip`, so pointing the adapter at
    `/inspect` left the whole suite green. In production a
    `RENDER_BASE_URL` with a trailing slash or an included `/render` yields
    `//render` or `/render/render` — a 404 from our own sidecar for every
    rendered page."""
    seen: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(str(req.url))
        return rendered()

    f = RenderServiceFetcher(
        base_url=SIDECAR + "/",
        clock=FakeClock(),
        client=RenderServiceFetcher.build_client(transport=httpx2.MockTransport(handler)),
    )
    try:
        await f.fetch(request())
    finally:
        await f.aclose()

    assert seen == [f"{SIDECAR}/render"]


async def test_the_transport_timeout_is_set_explicitly_and_covers_the_sidecar() -> None:
    """Deleting the `timeout=` kwarg left the suite green, and httpx2's
    default is **5 seconds** (measured) — so every render over 5 s would
    become `ReadTimeout` → `Backpressure`: RENDERED domains stalling for
    ever and AUTO domains degrading for ever, with nothing logged as an
    error.

    The transport budget must exceed the render budget, or the socket gives
    up before the sidecar can answer 503 or 504 and we lose the more useful
    reply."""
    seen: list[Mapping[str, float | None]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req.extensions["timeout"])
        return rendered()

    f = fetcher(handler)
    try:
        await f.fetch(request(timeout_ms=20_000))
    finally:
        await f.aclose()

    read = seen[0]["read"]
    assert read is not None
    assert read == pytest.approx(20 + TRANSPORT_HEADROOM_S)
    assert read > 20, "the socket would give up before the sidecar could answer"


async def test_the_render_budget_is_clamped_to_the_sidecars_own_ceiling() -> None:
    """Spec 012 §3 caps render time at 30 s and the sidecar enforces it
    (`render/src/limits.js`). Asking for more means waiting for a budget that
    cannot be spent — and with the 504 retry, one page could occupy a worker
    for longer than ADR-0026's 120-second lease, at which point the sweep
    returns the row while the fetch is still in flight and another worker
    takes the same URL. Two simultaneous requests to one host, reached
    through the mechanism meant to prevent them."""
    import json

    bodies: list[dict[str, object]] = []
    seen: list[Mapping[str, float | None]] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        seen.append(req.extensions["timeout"])
        return rendered()

    f = fetcher(handler)
    try:
        await f.fetch(request(timeout_ms=600_000))
    finally:
        await f.aclose()

    assert bodies[0]["timeout_ms"] == SIDECAR_MAX_TIMEOUT_MS
    read = seen[0]["read"]
    assert read is not None
    assert read == pytest.approx(SIDECAR_MAX_TIMEOUT_MS / 1000 + TRANSPORT_HEADROOM_S)


def test_two_attempts_fit_inside_the_claim_lease() -> None:
    """The arithmetic, asserted rather than reasoned about.

    `RENDER_TIMEOUT_RETRIES` means a page can take two full attempts. If that
    total can exceed spec 002 §1's 120-second lease, the sweep hands the row
    to another worker mid-fetch — the ADR-0026 failure, from the other
    direction. Any future change to the ceiling, the headroom or the retry
    count has to keep satisfying this.
    """
    attempts = RENDER_TIMEOUT_RETRIES + 1
    worst_case_s = attempts * (SIDECAR_MAX_TIMEOUT_MS / 1000 + TRANSPORT_HEADROOM_S)
    assert worst_case_s < LEASE_BUDGET_S, (
        f"{attempts} attempts can take {worst_case_s}s, which outlives the "
        f"{LEASE_BUDGET_S}s claim lease — the sweep would return the row to "
        "pending while the fetch is still running and another worker would "
        "fetch the same URL (ADR-0026)"
    )


async def test_aclose_closes_this_adapters_pool() -> None:
    """The mutation matrix's one honest dash: nothing asserted this. The
    composition's `aclose` test covers `AutoFetcher` calling both, not either
    adapter actually closing."""
    f = fetcher(lambda _: rendered())
    await f.fetch(request())
    await f.aclose()

    with pytest.raises(RuntimeError):
        await f.fetch(request())


def test_the_strategy_vocabulary_carries_static_fallback() -> None:
    """BUILD_PLAN 1.7's own deliverable, and deleting the enum member left
    the suite green — nothing referenced it. The string matters as much as
    the member: it is written into `page_observations.strategy`, which
    TESTING.md §2 asserts on by value when `render` is stopped."""
    from spydra.domain.enums import Strategy

    assert Strategy.STATIC_FALLBACK.value == "static_fallback"
    assert "static_fallback" in {s.value for s in Strategy}
