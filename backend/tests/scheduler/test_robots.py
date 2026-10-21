"""`robots.txt` handling, against `1.4`'s fixtures (BUILD_PLAN 1.9, spec 002 §5).

The fixtures are the real ones from `1.4`, read off disk rather than inlined:
`crawl-delay.txt` carries a comment saying it must raise a 2 s delay to 10 s
and must not lower a 30 s one, and a copy here would let the fixture drift
away from the test that depends on it.

The fetch goes through a fake `Fetcher` rather than the loopback server:
spec 002 §5's rules are about what we do with the *response*, and the
fail-closed branches need a 5xx and a `FetchFailed` that a static file server
cannot produce.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spydra.domain.enums import FetchPath
from spydra.domain.errors import FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.scheduler.politeness import PolitenessGate
from spydra.scheduler.robots import RobotsCache

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "robots"
UA = "MySampleScraper/1.0 (+https://jagadishk.work; k.jagdish@gmail.com)"
RUN = 1


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


class FakeFetcher:
    """Answers `/robots.txt` with a canned status and body."""

    path = FetchPath.STATIC

    def __init__(self, status: int = 200, body: str = "", raises: Exception | None = None) -> None:
        self._status = status
        self._body = body
        self._raises = raises
        self.urls: list[str] = []
        self.user_agents: list[str] = []

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        self.urls.append(request.url)
        self.user_agents.append(request.user_agent)
        if self._raises is not None:
            raise self._raises
        return FetchedPage(
            request_url=request.url,
            final_url=request.url,
            http_status=self._status,
            body=self._body,
            headers={},
            fetched_at=datetime(2026, 10, 21, 14, 0, tzinfo=UTC),
            elapsed_ms=10,
            fetch_path=self.path,
        )

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# F1, F2 — the floor, end to end through the real fixture
# ---------------------------------------------------------------------------


async def test_the_crawl_delay_fixture_raises_a_two_second_delay_to_ten() -> None:
    """Spec 002 §9's acceptance line, against `1.4`'s own file."""
    fetcher = FakeFetcher(200, fixture("crawl-delay"))
    rules = await RobotsCache(fetcher).rules_for(RUN, "crawl-delay.test", UA)

    assert rules.crawl_delay_s == 10.0
    assert PolitenessGate.apply_robots_floor(2000, rules.crawl_delay_s) == 10_000
    # ...and the other direction, which is what makes it a floor.
    assert PolitenessGate.apply_robots_floor(30_000, rules.crawl_delay_s) == 30_000


async def test_the_permissive_fixture_states_no_delay() -> None:
    """So a domain's configured delay stands. `None` here means "no floor",
    not "no delay" — reading it as zero would speed every crawl up to as
    fast as the worker can go."""
    rules = await RobotsCache(FakeFetcher(200, fixture("permissive"))).rules_for(
        RUN, "vantage-abrasives.test", UA
    )
    assert rules.crawl_delay_s is None
    assert rules.allowed_at_all is True
    assert PolitenessGate.apply_robots_floor(2000, rules.crawl_delay_s) == 2000


# ---------------------------------------------------------------------------
# F6 — Disallow
# ---------------------------------------------------------------------------


async def test_disallow_all_blocks_every_url() -> None:
    rules = await RobotsCache(FakeFetcher(200, fixture("disallow-all"))).rules_for(
        RUN, "disallow-all.test", UA
    )
    assert rules.can_fetch("https://disallow-all.test/catalog/a") is False
    assert rules.can_fetch("https://disallow-all.test/") is False


async def test_a_disallowed_path_is_blocked_while_the_rest_of_the_site_is_not() -> None:
    """`crawl-delay.txt` also carries `Disallow: /cart/`. A rules object that
    answered the delay correctly and ignored `Disallow` would pass every
    other test in this file."""
    rules = await RobotsCache(FakeFetcher(200, fixture("crawl-delay"))).rules_for(
        RUN, "crawl-delay.test", UA
    )
    assert rules.can_fetch("https://crawl-delay.test/cart/checkout") is False
    assert rules.can_fetch("https://crawl-delay.test/catalog/discs") is True


async def test_our_user_agent_token_is_preferred_over_the_wildcard() -> None:
    """Spec 002 §5: "honoured for the configured user-agent, falling back to
    `*`". A site that singles us out must be obeyed over its general rule —
    and in the permissive direction too, or an operator who negotiated access
    would still be blocked by the wildcard."""
    body = "User-agent: *\nDisallow: /\n\nUser-agent: MySampleScraper\nAllow: /\nCrawl-delay: 3\n"
    rules = await RobotsCache(FakeFetcher(200, body)).rules_for(RUN, "x.test", "MySampleScraper")
    assert rules.can_fetch("https://x.test/catalog") is True
    assert rules.crawl_delay_s == 3.0


# ---------------------------------------------------------------------------
# F3, F4 — and the direction each one fails in
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 403, 410])
async def test_a_4xx_means_no_restrictions(status: int) -> None:
    """Spec 002 §5. No file, or no permission to read it, is not a refusal."""
    rules = await RobotsCache(FakeFetcher(status, "")).rules_for(RUN, "x.test", UA)
    assert rules.allowed_at_all is True
    assert rules.can_fetch("https://x.test/anything") is True


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_5xx_fails_closed_and_skips_the_domain_for_the_run(status: int) -> None:
    """Spec 002 §5: "failing closed is correct when the site cannot tell you
    its rules". The alternative is crawling a site that was about to say
    don't — and this is the one place in the system where the safe direction
    is to do *less* work rather than more."""
    rules = await RobotsCache(FakeFetcher(status, "")).rules_for(RUN, "x.test", UA)
    assert rules.allowed_at_all is False
    assert rules.can_fetch("https://x.test/catalog") is False


async def test_a_fetch_failure_fails_closed_too() -> None:
    """Spec 002 §5 names "a 5xx or a timeout", and a `FetchFailed` from the
    port **is** the timeout case. Left unhandled it would not fail closed —
    it would escape into the claim loop."""
    fetcher = FakeFetcher(raises=FetchFailed("connection refused"))
    rules = await RobotsCache(fetcher).rules_for(RUN, "x.test", UA)
    assert rules.allowed_at_all is False


# ---------------------------------------------------------------------------
# F5, F7 — once per run, and the override
# ---------------------------------------------------------------------------


async def test_robots_is_fetched_once_per_domain_per_run() -> None:
    """Spec 002 §5: "once per domain per run, cached for the run's duration".
    Asserted on the number of **fetches**, not on the answer — a cache that
    re-fetched every time would return the same answer and pass any
    assertion about the result."""
    fetcher = FakeFetcher(200, fixture("crawl-delay"))
    cache = RobotsCache(fetcher)

    for _ in range(5):
        await cache.rules_for(RUN, "crawl-delay.test", UA)
    await cache.rules_for(RUN, "other.test", UA)

    assert cache.fetch_count == 2, "one per domain, not one per call"
    assert len(fetcher.urls) == 2


async def test_a_second_run_re_reads_the_file() -> None:
    """Keyed by (run, host), not host. A site that changed its rules between
    runs would otherwise be crawled against the old ones for as long as the
    process lives — and this process is a long-running worker."""
    fetcher = FakeFetcher(200, fixture("permissive"))
    cache = RobotsCache(fetcher)

    await cache.rules_for(1, "x.test", UA)
    await cache.rules_for(2, "x.test", UA)

    assert cache.fetch_count == 2


async def test_robots_is_fetched_with_our_honest_user_agent() -> None:
    """ADR-0004 applies to this request too. Fetching `robots.txt` as
    something else, and then obeying the rules for our real token, would be
    asking one question and answering another."""
    fetcher = FakeFetcher(200, fixture("permissive"))
    await RobotsCache(fetcher).rules_for(RUN, "x.test", UA)

    assert fetcher.user_agents == [UA]
    assert fetcher.urls == ["https://x.test/robots.txt"]


async def test_respect_robots_false_overrides_and_logs_every_time() -> None:
    """Spec 002 §5: "an operator override, **logged every time it takes
    effect**".

    Every time, not once per run: the operator chose to ignore a site's
    stated rules, and each crawl under that override should be attributable.
    So the assertion is on the log count, and it is why the override is
    checked before the cache rather than after."""
    fetcher = FakeFetcher(200, fixture("disallow-all"))
    cache = RobotsCache(fetcher)

    # Its own handler on the module's logger rather than `caplog`.
    #
    # `caplog` attaches to the ROOT logger and so depends on propagation. It
    # passed in isolation and failed in the full suite, where something else
    # had configured logging — a cross-test interaction, and the worst kind,
    # because the failing assertion ("logged every time") reads like a defect
    # in the code under test. Attaching here makes the test independent of
    # whatever else the suite has done to logging.
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("spydra.scheduler.robots")
    handler = Capture()
    previous_level = logger.level
    logger.addHandler(handler)
    # All four, because three of them were not enough.
    #
    # Measured in the full suite: `isEnabledFor(WARNING)` returned False while
    # the effective level was 30 and `logging.disable` was 0 — a stale entry
    # in `Logger._cache`, left by another test's logging manipulation.
    # `logging` caches enablement per level and only invalidates it on some
    # paths, so a test that merely sets a level can still be silently muted
    # by whatever ran before it. Clearing the cache is the part that actually
    # fixed it.
    logging.disable(logging.NOTSET)
    logger.disabled = False
    logger.setLevel(logging.DEBUG)
    # `Manager._clear_cache` is not in the typeshed stubs, hence the ignore;
    # it is the documented invalidation hook that `setLevel` itself calls.
    logging.Logger.manager._clear_cache()  # type: ignore[attr-defined]
    assert logger.isEnabledFor(logging.WARNING), "the logger is muted before we start"
    try:
        for _ in range(3):
            rules = await cache.rules_for(RUN, "disallow-all.test", UA, respect_robots=False)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert rules.allowed_at_all is True
    assert rules.can_fetch("https://disallow-all.test/anything") is True
    assert cache.fetch_count == 0, "the override must not even ask"
    overrides = [r for r in records if r.getMessage() == "robots_override"]
    assert len(overrides) == 3, "logged every time it takes effect, not once"
