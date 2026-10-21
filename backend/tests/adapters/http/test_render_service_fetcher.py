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

from collections.abc import Callable
from datetime import UTC, datetime

import httpx2
import pytest

from spydra.adapters.http import RenderServiceFetcher
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


def request(**kw: object) -> FetchRequest:
    kw.setdefault("url", PAGE_URL)
    kw.setdefault("user_agent", "MySampleScraper/1.0 (+https://jagadishk.work)")
    return FetchRequest(**kw)  # type: ignore[arg-type]  # kwargs are checked by the dataclass


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


@pytest.mark.parametrize("status", [502, 422, 500, 404])
async def test_other_sidecar_errors_are_fetch_failures(status: int) -> None:
    """502 is a navigation failure, 422 is a bug in our own request body, and
    anything else is unexpected. None of them is backpressure, and none
    improves on a retry."""

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
