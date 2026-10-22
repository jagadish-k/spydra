"""One claimed URL, crawled: every outcome in the 1.13 contract's table
(BUILD_PLAN 1.13, spec 002 §2–§6, ADR-0004, spec 012 §4).

**Real Postgres, real repositories, real gate; fake fetchers.** The outcome
of a crawl is rows — the queue row, the domain row, observations, the inbox —
so those are what is asserted, read back with SQL. The fetchers are fakes
behind the `Fetcher` port (hand-written, ADR-0028) because a 403, a 429 and
a request that never got a response are statuses the fixture server does not
produce. The sidecar's 503 goes through the real `RenderServiceFetcher` over
`httpx2.MockTransport`, since "a 503 from the sidecar" is the criterion and
translating it is that adapter's job.

**The gate's delay is skipped by moving `next_eligible_at` into the past
between claims.** Nothing here is about the gap between requests (that is
`test_politeness_observed.py`); these tests are about what each outcome
writes, and waiting out a real delay would only make them slow.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx2
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.auto_fetcher import AutoFetcher
from spydra.adapters.http.render_service_fetcher import RenderServiceFetcher
from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.domains import PostgresDomains
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.adapters.postgres.pages import PostgresPages
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.adapters.postgres.templates import PostgresTemplates, extraction_to_json
from spydra.domain.enums import FetchPath, RenderMode
from spydra.domain.errors import FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.domain.ids import DomainId, RunId
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.observations.writer import ObservationWriter
from spydra.ports.fetcher import Fetcher
from spydra.ports.frontier import ClaimedUrl
from spydra.scheduler.crawl import Fetchers, PageCrawler, Repositories
from spydra.scheduler.politeness import PolitenessGate
from spydra.scheduler.render_budget import RenderBudget
from spydra.scheduler.robots import RobotsCache
from tests.adapters.postgres.observation_seed import unknown_rows
from tests.adapters.postgres.seed import (
    domain_row,
    queue_row,
    seed_domain,
    seed_queue_row,
    seed_run,
)
from tests.extraction.pages import PAGES, vantage_template

pytestmark = pytest.mark.integration

UA = "SpydraTest/1.0 (+https://spydra.test)"
HOST = "vantage-abrasives.test"
BASE = f"https://{HOST}"

PRODUCT = (PAGES / "vantage-abrasives/product.html").read_text()
IMAGE_STUB = (PAGES / "vantage-abrasives/product-image-stub.html").read_text()

Response = FetchedPage | Exception


def _page(request: FetchRequest, status: int, body: str, path: FetchPath) -> FetchedPage:
    return FetchedPage(
        request_url=request.url,
        final_url=request.url,
        http_status=status,
        body=body,
        headers={},
        fetched_at=datetime.now(UTC),
        elapsed_ms=5,
        fetch_path=path,
    )


class ScriptedFetcher:
    """A `Fetcher` whose answer per URL is decided by the test.

    `robots.txt` is answered 404 (no restrictions, spec 002 §5) and not
    recorded in `calls`, so `calls` is the page requests and nothing else.
    """

    def __init__(
        self,
        path: FetchPath,
        answer: Callable[[FetchRequest], tuple[int, str] | Exception],
    ) -> None:
        self.path = path
        self._answer = answer
        self.calls: list[str] = []

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        if request.url.endswith("/robots.txt"):
            return _page(request, 404, "", self.path)
        self.calls.append(request.url)
        answer = self._answer(request)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return _page(request, status, body, self.path)

    async def aclose(self) -> None:
        pass


def always(status: int, body: str = "") -> Callable[[FetchRequest], tuple[int, str]]:
    return lambda _request: (status, body)


def raising(exc: Exception) -> Callable[[FetchRequest], Exception]:
    return lambda _request: exc


def build(engine: AsyncEngine, static: Fetcher, rendered: Fetcher) -> PageCrawler:
    """A `PageCrawler` wired the way `spydra.worker` wires it, over these
    two fetchers."""
    clock = SystemClock()
    observations = PostgresObservations(engine)
    return PageCrawler(
        frontier=PostgresFrontier(engine),
        repositories=Repositories(
            domains=PostgresDomains(engine),
            pages=PostgresPages(engine),
            templates=PostgresTemplates(engine),
            observations=observations,
            runs=PostgresRuns(engine),
        ),
        writer=ObservationWriter(observations, PostgresAssets(engine)),
        chain=ExtractionChain([StructuredStrategy(), SelectorStrategy()]),
        gate=PolitenessGate(clock),
        robots=RobotsCache(static),
        fetchers=Fetchers(static=static, rendered=rendered, auto=AutoFetcher(static, rendered)),
        user_agent=UA,
    )


def unused_renderer() -> ScriptedFetcher:
    return ScriptedFetcher(FetchPath.RENDERED, raising(AssertionError("sidecar not expected")))


async def seed_crawl_domain(
    engine: AsyncEngine,
    *,
    mode: RenderMode = RenderMode.STATIC,
    crawl_delay_ms: int = 2000,
    configured_crawl_delay_ms: int = 2000,
    with_template: bool = False,
) -> DomainId:
    domain = await seed_domain(engine, HOST, crawl_delay_ms=crawl_delay_ms)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.domains SET render_mode = :mode, configured_crawl_delay_ms = :floor "
                "WHERE id = :id"
            ),
            {"mode": mode.value, "floor": configured_crawl_delay_ms, "id": int(domain)},
        )
        if with_template:
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO crawl.templates
                        (domain_id, name, url_pattern, page_kind, version, is_active,
                         extraction, approved_at)
                    VALUES (:d, 'vantage product', '/catalog/.+', 'product', 1, true,
                            CAST(:x AS jsonb), now())
                    """
                ),
                {
                    "d": int(domain),
                    "x": json.dumps(extraction_to_json(vantage_template().extraction)),
                },
            )
    return domain


async def make_due(engine: AsyncEngine, domain: DomainId) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.domains SET next_eligible_at = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": int(domain)},
        )


async def claim_and_crawl(
    engine: AsyncEngine, crawler: PageCrawler, domain: DomainId
) -> ClaimedUrl:
    await make_due(engine, domain)
    item = await PostgresFrontier(engine).claim()
    assert item is not None, "nothing claimable"
    await crawler.crawl(item)
    return item


async def observation_statuses(engine: AsyncEngine, domain: DomainId) -> list[int]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        """
                        SELECT o.http_status FROM crawl.page_observations o
                        JOIN crawl.pages p ON p.id = o.page_id
                        WHERE p.domain_id = :d ORDER BY o.id
                        """
                    ),
                    {"d": int(domain)},
                )
            ).scalars()
        )


async def queue_states(engine: AsyncEngine, run: RunId) -> list[str]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text("SELECT state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id"),
                    {"r": int(run)},
                )
            ).scalars()
        )


# ---------------------------------------------------------------------------
# No response, and the supplier's own failures: retried, then failed
# ---------------------------------------------------------------------------


async def _three_attempts(
    engine: AsyncEngine, answer: Callable[[FetchRequest], tuple[int, str] | Exception]
) -> tuple[DomainId, int, str]:
    domain = await seed_crawl_domain(engine)
    run = await seed_run(engine, [int(domain)])
    url = f"{BASE}/catalog/abrasives/discs/rfd-115-060"
    row = await seed_queue_row(engine, run, domain, url)
    static = ScriptedFetcher(FetchPath.STATIC, answer)
    crawler = build(engine, static, unused_renderer())

    for attempt in (1, 2):
        await claim_and_crawl(engine, crawler, domain)
        state = await queue_row(engine, row)
        assert (state.state, state.attempts) == ("pending", attempt), "retried until 3 attempts"
        assert await unknown_rows(engine, domain) == [], "inbox only once the row has failed"
        assert (await domain_row(engine, domain)).in_flight == 0

    await claim_and_crawl(engine, crawler, domain)
    assert len(static.calls) == 3
    return domain, row, url


async def test_a_request_with_no_response_three_times_fails_with_one_fetch_error_inbox_row(
    clean_crawl: AsyncEngine,
) -> None:
    domain, row, url = await _three_attempts(clean_crawl, raising(FetchFailed("refused")))

    assert (await queue_row(clean_crawl, row)).state == "failed"
    assert [(r.url, r.reason) for r in await unknown_rows(clean_crawl, domain)] == [
        (url, "fetch_error")
    ]
    assert await observation_statuses(clean_crawl, domain) == []
    assert (await domain_row(clean_crawl, domain)).in_flight == 0


@pytest.mark.parametrize("status", [500, 502, 503, 429])
async def test_a_server_failure_three_times_fails_with_one_fetch_error_inbox_row_and_no_observation(
    clean_crawl: AsyncEngine, status: int
) -> None:
    """An outage or a rate limit is a fact about the request, not the page:
    no observation, and the page goes to the inbox once it has run out."""
    domain, row, url = await _three_attempts(clean_crawl, always(status, "<h1>Error</h1>"))

    assert (await queue_row(clean_crawl, row)).state == "failed"
    assert [(r.url, r.reason) for r in await unknown_rows(clean_crawl, domain)] == [
        (url, "fetch_error")
    ]
    assert await observation_statuses(clean_crawl, domain) == []


async def test_a_404_is_done_with_an_observation_and_no_inbox_row(
    clean_crawl: AsyncEngine,
) -> None:
    """A dead link is a fact about the page, and not a template problem."""
    domain = await seed_crawl_domain(clean_crawl, with_template=True)
    run = await seed_run(clean_crawl, [int(domain)])
    row = await seed_queue_row(clean_crawl, run, domain, f"{BASE}/catalog/gone")
    crawler = build(
        clean_crawl,
        ScriptedFetcher(FetchPath.STATIC, always(404, "<h1>Not found</h1>")),
        unused_renderer(),
    )

    await claim_and_crawl(clean_crawl, crawler, domain)

    assert (await queue_row(clean_crawl, row)).state == "done"
    assert await observation_statuses(clean_crawl, domain) == [404]
    assert await unknown_rows(clean_crawl, domain) == []
    assert (await domain_row(clean_crawl, domain)).in_flight == 0


# ---------------------------------------------------------------------------
# 403: never retried; three in a row stop the domain (ADR-0004)
# ---------------------------------------------------------------------------


async def test_a_403_fails_the_row_at_once_with_no_observation(clean_crawl: AsyncEngine) -> None:
    domain = await seed_crawl_domain(clean_crawl, with_template=True)
    run = await seed_run(clean_crawl, [int(domain)])
    row = await seed_queue_row(clean_crawl, run, domain, f"{BASE}/catalog/a")
    static = ScriptedFetcher(FetchPath.STATIC, always(403, "<h1>Access denied</h1>"))
    crawler = build(clean_crawl, static, unused_renderer())

    await claim_and_crawl(clean_crawl, crawler, domain)

    state = await queue_row(clean_crawl, row)
    assert (state.state, state.attempts) == ("failed", 1), "a 403 is never retried"
    assert static.calls == [f"{BASE}/catalog/a"]
    assert await observation_statuses(clean_crawl, domain) == []
    after = await domain_row(clean_crawl, domain)
    assert after.state == "active", "one refusal does not pause"
    assert after.in_flight == 0


async def test_three_consecutive_403s_pause_the_domain_and_abandon_its_rows(
    clean_crawl: AsyncEngine,
) -> None:
    domain = await seed_crawl_domain(clean_crawl, with_template=True)
    run = await seed_run(clean_crawl, [int(domain)])
    for n in range(5):
        await seed_queue_row(clean_crawl, run, domain, f"{BASE}/catalog/p{n}")
    static = ScriptedFetcher(FetchPath.STATIC, always(403, "<h1>Access denied</h1>"))
    crawler = build(clean_crawl, static, unused_renderer())

    for _ in range(3):
        await claim_and_crawl(clean_crawl, crawler, domain)

    after = await domain_row(clean_crawl, domain)
    assert after.state == "paused"
    assert after.in_flight == 0
    assert await queue_states(clean_crawl, run) == [
        "failed",
        "failed",
        "failed",
        "abandoned",
        "abandoned",
    ]
    assert await observation_statuses(clean_crawl, domain) == []
    assert len(static.calls) == 3, "nothing further was requested from a blocking site"
    await make_due(clean_crawl, domain)
    assert await PostgresFrontier(clean_crawl).claim() is None


# ---------------------------------------------------------------------------
# Our own sidecar is full: released, no penalty (spec 002 §6)
# ---------------------------------------------------------------------------


async def test_a_503_from_the_sidecar_releases_the_row_with_no_attempt_charged(
    clean_crawl: AsyncEngine,
) -> None:
    domain = await seed_crawl_domain(clean_crawl, mode=RenderMode.RENDERED)
    run = await seed_run(clean_crawl, [int(domain)])
    row = await seed_queue_row(clean_crawl, run, domain, f"{BASE}/catalog/a")
    before = await domain_row(clean_crawl, domain)

    sidecar_calls: list[str] = []

    def full(request: httpx2.Request) -> httpx2.Response:
        sidecar_calls.append(str(request.url))
        return httpx2.Response(503, json={"error": "no context available"})

    sidecar = RenderServiceFetcher(
        "http://render.test:3000",
        SystemClock(),
        client=RenderServiceFetcher.build_client(httpx2.MockTransport(full)),
    )
    static = ScriptedFetcher(FetchPath.STATIC, raising(AssertionError("static not expected")))
    crawler = build(clean_crawl, static, RenderBudget(sidecar, 1))

    await claim_and_crawl(clean_crawl, crawler, domain)

    assert sidecar_calls, "the page never reached the sidecar"
    state = await queue_row(clean_crawl, row)
    assert (state.state, state.attempts) == ("pending", 0)
    after = await domain_row(clean_crawl, domain)
    assert after.in_flight == 0, "the gate was not given back"
    assert after.consecutive_failures == before.consecutive_failures
    assert after.crawl_delay_ms == before.crawl_delay_ms
    assert await unknown_rows(clean_crawl, domain) == []
    await sidecar.aclose()


# ---------------------------------------------------------------------------
# AUTO's second chance (spec 012 §4)
# ---------------------------------------------------------------------------


async def test_auto_renders_once_when_the_static_page_has_nothing_usable(
    clean_crawl: AsyncEngine,
) -> None:
    """The image-only stub is not empty (an image resolved) but it is not
    substantive either, and that must still earn the browser retry. Exactly
    one: the rendered page is no better here, and that is not a reason to
    ask again."""
    domain = await seed_crawl_domain(clean_crawl, mode=RenderMode.AUTO)
    run = await seed_run(clean_crawl, [int(domain)])
    url = f"{BASE}/catalog/abrasives/discs/rfd-115-060"
    row = await seed_queue_row(clean_crawl, run, domain, url)
    static = ScriptedFetcher(FetchPath.STATIC, always(200, IMAGE_STUB))
    rendered = ScriptedFetcher(FetchPath.RENDERED, always(200, IMAGE_STUB))
    crawler = build(clean_crawl, static, rendered)

    await claim_and_crawl(clean_crawl, crawler, domain)

    assert static.calls == [url]
    assert rendered.calls == [url]
    assert (await queue_row(clean_crawl, row)).state == "done"


async def test_auto_does_not_render_a_substantive_static_page(clean_crawl: AsyncEngine) -> None:
    domain = await seed_crawl_domain(clean_crawl, mode=RenderMode.AUTO, with_template=True)
    run = await seed_run(clean_crawl, [int(domain)])
    url = f"{BASE}/catalog/abrasives/discs/rfd-115-060"
    await seed_queue_row(clean_crawl, run, domain, url)
    rendered = ScriptedFetcher(FetchPath.RENDERED, always(200, PRODUCT))
    crawler = build(clean_crawl, ScriptedFetcher(FetchPath.STATIC, always(200, PRODUCT)), rendered)

    await claim_and_crawl(clean_crawl, crawler, domain)

    assert rendered.calls == []


@pytest.mark.parametrize("status", [404, 403, 500])
async def test_auto_never_renders_after_a_non_200(clean_crawl: AsyncEngine, status: int) -> None:
    """A refusal or an error page extracts nothing, and rendering it would be
    a second request inside one claim: a retry through a block (ADR-0004)."""
    domain = await seed_crawl_domain(clean_crawl, mode=RenderMode.AUTO)
    run = await seed_run(clean_crawl, [int(domain)])
    await seed_queue_row(clean_crawl, run, domain, f"{BASE}/catalog/a")
    rendered = ScriptedFetcher(FetchPath.RENDERED, always(200, PRODUCT))
    crawler = build(
        clean_crawl, ScriptedFetcher(FetchPath.STATIC, always(status, IMAGE_STUB)), rendered
    )

    await claim_and_crawl(clean_crawl, crawler, domain)

    assert rendered.calls == []


# ---------------------------------------------------------------------------
# The decay floor (spec 002 §4, 1.9 open question 1)
# ---------------------------------------------------------------------------


async def _delays_after_429_then_successes(
    engine: AsyncEngine, *, configured: int, robots: str | None, successes: int = 30
) -> tuple[int, list[int]]:
    domain = await seed_crawl_domain(
        engine, crawl_delay_ms=configured, configured_crawl_delay_ms=configured, with_template=True
    )
    run = await seed_run(engine, [int(domain)])
    for n in range(successes + 1):
        await seed_queue_row(engine, run, domain, f"{BASE}/catalog/p{n}")

    first = [True]

    def answer(_request: FetchRequest) -> tuple[int, str]:
        if first[0]:
            first[0] = False
            return 429, "<h1>Slow down</h1>"
        return 200, PRODUCT

    class WithRobots(ScriptedFetcher):
        async def fetch(self, request: FetchRequest) -> FetchedPage:
            if robots is not None and request.url.endswith("/robots.txt"):
                return _page(request, 200, robots, self.path)
            return await super().fetch(request)

    crawler = build(engine, WithRobots(FetchPath.STATIC, answer), unused_renderer())

    await claim_and_crawl(engine, crawler, domain)
    backed_off = (await domain_row(engine, domain)).crawl_delay_ms
    delays = []
    for _ in range(successes):
        await claim_and_crawl(engine, crawler, domain)
        delays.append((await domain_row(engine, domain)).crawl_delay_ms)
    return backed_off, delays


async def test_successes_decay_a_backed_off_delay_but_never_below_the_configured_one(
    clean_crawl: AsyncEngine,
) -> None:
    configured = 1000
    backed_off, delays = await _delays_after_429_then_successes(
        clean_crawl, configured=configured, robots=None
    )

    assert backed_off > configured, "the 429 did not back off"
    assert delays[0] < backed_off, "a success did not decay the delay"
    assert all(later <= earlier for earlier, later in zip(delays, delays[1:], strict=False))
    assert min(delays) >= configured, f"decayed below the operator's delay: {delays}"
    assert delays[-1] == configured, "the decay should settle on the configured delay"


async def test_the_decay_floor_is_robots_crawl_delay_when_that_is_higher(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 002 §5: the site's `Crawl-delay` is a floor too. The decay
    stops there, not at the lower value the operator configured."""
    backed_off, delays = await _delays_after_429_then_successes(
        clean_crawl, configured=1000, robots="User-agent: *\nCrawl-delay: 3\n"
    )

    assert backed_off > 3000
    assert min(delays) >= 3000, f"decayed below the site's Crawl-delay: {delays}"
    assert delays[-1] == 3000
