"""`AutoFetcher` — spec 012 §4's AUTO mode (BUILD_PLAN 1.7).

Two fakes behind the `Fetcher` port, not the real adapters. That is the point
of ADR-0008 here: this composition does not know a browser exists on one
side, so a test does not need one either.

**Only the sidecar-unavailable half of AUTO is built**, and so only that half
is tested. The extraction-driven retry needs `empty_extraction` from spec 003
§3 (`1.10`) and the worker orchestration (`1.13`). Asserting it here would
mean inventing a predicate for "nothing usable", which is the failure
ADR-0027 removed requiredness to avoid.
"""

from datetime import UTC, datetime

import pytest

from spydra.adapters.http import AutoFetcher
from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest

FIXED_NOW = datetime(2026, 10, 21, 11, 40, tzinfo=UTC)
PAGE_URL = "https://mertens.test/katalog/stirnlochschluessel-30-80"


def page(path: FetchPath, body: str) -> FetchedPage:
    return FetchedPage(
        request_url=PAGE_URL,
        final_url=PAGE_URL,
        http_status=200,
        body=body,
        headers={},
        fetched_at=FIXED_NOW,
        elapsed_ms=120,
        fetch_path=path,
    )


class FakeFetcher:
    """A `Fetcher` that returns a page, or raises what it was given."""

    def __init__(self, path: FetchPath, body: str = "ok", raises: Exception | None = None) -> None:
        self.path = path
        self._body = body
        self._raises = raises
        self.calls = 0
        self.closed = False

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return page(self.path, self._body)

    async def aclose(self) -> None:
        self.closed = True


def request() -> FetchRequest:
    return FetchRequest(url=PAGE_URL, user_agent="MySampleScraper/1.0 (+https://x.test)")


def auto(static: FakeFetcher, rendered: FakeFetcher) -> AutoFetcher:
    return AutoFetcher(static=static, rendered=rendered)


# ---------------------------------------------------------------------------


async def test_auto_fetches_statically_first_and_does_not_touch_the_sidecar() -> None:
    """Spec 012 §4: static first, because it is the cheap path, and "one
    wasted cheap fetch" is the stated cost of a wrong onboarding guess. An
    AUTO domain that rendered every page would make the mode pointless."""
    static = FakeFetcher(FetchPath.STATIC, body="static body")
    rendered = FakeFetcher(FetchPath.RENDERED, body="rendered body")

    result = await auto(static, rendered).fetch(request())

    assert result.body == "static body"
    assert result.fetch_path is FetchPath.STATIC
    assert result.fell_back_from is None, "nothing was degraded, so nothing to record"
    assert rendered.calls == 0, "the sidecar was called on the cheap path"


async def test_a_static_fetch_failure_propagates_rather_than_falling_back() -> None:
    """A dead supplier is not a sidecar problem. Converting this into a
    degraded success would hide a real failure behind a fake recovery, and
    the politeness gate would never see the failure it needs to count."""
    static = FakeFetcher(FetchPath.STATIC, raises=FetchFailed("refused"))
    rendered = FakeFetcher(FetchPath.RENDERED)

    with pytest.raises(FetchFailed):
        await auto(static, rendered).fetch(request())

    assert rendered.calls == 0


async def test_the_second_chance_returns_the_rendered_page_when_the_sidecar_works() -> None:
    static = FakeFetcher(FetchPath.STATIC, body="static body")
    rendered = FakeFetcher(FetchPath.RENDERED, body="rendered body")
    already = page(FetchPath.STATIC, "static body")

    result = await auto(static, rendered).fetch_rendered_or_fall_back(request(), already)

    assert result.body == "rendered body"
    assert result.fetch_path is FetchPath.RENDERED
    assert result.fell_back_from is None
    assert static.calls == 0, "the static page was handed in; it must not be fetched again"


async def test_backpressure_on_the_second_chance_falls_back_and_records_it() -> None:
    """The criterion TESTING.md §2 asserts when `render` is stopped: an AUTO
    domain keeps crawling and the fallback is **recorded**, which is what
    `1.11` writes as `strategy = static_fallback`.

    `fell_back_from` rather than `fetch_path` carries it because AUTO fetches
    static first by design, so `fetch_path = STATIC` is the healthy outcome
    too — the two are indistinguishable from that field alone."""
    static = FakeFetcher(FetchPath.STATIC, body="static body")
    rendered = FakeFetcher(FetchPath.RENDERED, raises=Backpressure("sidecar full"))
    already = page(FetchPath.STATIC, "static body")

    result = await auto(static, rendered).fetch_rendered_or_fall_back(request(), already)

    assert result.body == "static body"
    assert result.fetch_path is FetchPath.STATIC
    assert result.fell_back_from is FetchPath.RENDERED
    assert result.degraded is True
    # THE POLITENESS ASSERTION. The first version re-fetched statically here,
    # which is a second request to the supplier inside the same claim — and
    # spec 002 §2 advances `next_eligible_at` only after a fetch completes,
    # so it leaves with no politeness gap at all. On a 3,400-page AUTO domain
    # with `render` stopped that is 6,800 requests instead of 3,400, at
    # double the configured per-host rate, returning a page extraction has
    # already rejected as empty.
    assert static.calls == 0, (
        "the fallback re-fetched the supplier. The static page was already in "
        "hand, and a second request inside one claim has no politeness gap"
    )


async def test_the_fallback_keeps_every_other_field_of_the_static_page() -> None:
    """The fallback rebuilds the page to add one field. A rebuild that drops
    `http_status` or `final_url` would be invisible here unless asserted —
    and `1.9` reads the status to decide backoff."""
    static = FakeFetcher(FetchPath.STATIC, body="static body")
    rendered = FakeFetcher(FetchPath.RENDERED, raises=Backpressure("full"))
    original = page(FetchPath.STATIC, "static body")

    result = await auto(static, rendered).fetch_rendered_or_fall_back(request(), original)

    for field in ("request_url", "final_url", "http_status", "headers", "fetched_at", "elapsed_ms"):
        assert getattr(result, field) == getattr(original, field), field


async def test_a_rendered_fetch_failure_is_not_a_fallback() -> None:
    """`Backpressure` means the sidecar could not take the work. `FetchFailed`
    means it tried and the page did not render — falling back on that would
    silently substitute static data for a page that genuinely needs a
    browser, and the operator would never learn the render path is broken."""
    static = FakeFetcher(FetchPath.STATIC, body="static body")
    rendered = FakeFetcher(FetchPath.RENDERED, raises=FetchFailed("502 from the sidecar"))
    already = page(FetchPath.STATIC, "static body")

    with pytest.raises(FetchFailed):
        await auto(static, rendered).fetch_rendered_or_fall_back(request(), already)

    assert static.calls == 0, "a failed render should not quietly become a static page"


async def test_aclose_closes_both_pools() -> None:
    """Closing one and leaking the other shows up in `1.13` as a hung
    SIGTERM rather than as an error."""
    static = FakeFetcher(FetchPath.STATIC)
    rendered = FakeFetcher(FetchPath.RENDERED)

    await auto(static, rendered).aclose()

    assert static.closed and rendered.closed


def test_auto_satisfies_the_fetcher_protocol() -> None:
    from spydra.ports.fetcher import Fetcher

    composed: Fetcher = AutoFetcher(
        static=FakeFetcher(FetchPath.STATIC),
        rendered=FakeFetcher(FetchPath.RENDERED),
    )
    assert composed.path is FetchPath.STATIC
