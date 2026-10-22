"""`rel="canonical"` collapses two URLs into one page row (spec 004 §5,
BUILD_PLAN 2.2).

**Real Postgres, real `PageCrawler`, the real static fetcher, Halden over
loopback.** The fixture serves one product at two URLs:
`/shop/cutting/blades/p/<sku>` names `/shop/p/<sku>` as its canonical, and
the canonical names itself. Crawling both in one run must leave ONE `pages`
row, under the canonical URL, holding both observations. A polish product
names a canonical on another host. That must be ignored, and the page kept
under its own URL.

The domain is the fixture site's `127.0.0.1:<port>`, so Halden's relative
canonical resolves onto the same host the crawl is on, the way it would on
the real site. The gate's delay is skipped by moving `next_eligible_at`
into the past between claims, as `test_page_crawler.py` does: this file is
about which row a page lands in, not the gap between requests.
"""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.auto_fetcher import AutoFetcher
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.domains import PostgresDomains
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.adapters.postgres.pages import PostgresPages
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.adapters.postgres.templates import PostgresTemplates
from spydra.domain.enums import FetchPath
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.domain.ids import DomainId, RunId
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.observations.writer import ObservationWriter
from spydra.scheduler.crawl import Fetchers, PageCrawler, Repositories
from spydra.scheduler.politeness import PolitenessGate
from spydra.scheduler.robots import RobotsCache
from tests.adapters.postgres.seed import seed_domain, seed_run
from tests.fixtures.server import FixtureSite

pytestmark = [
    pytest.mark.integration,
    # `<link rel="canonical">` is read as RDFa by extruct's pyRdfa, whose
    # warning path calls the deprecated `datetime.utcnow()`. Under the
    # suite's `filterwarnings = ["error"]` that raises inside the structured
    # rung, so every Halden page with a canonical would crash the crawl here
    # for a reason unrelated to 2.2. Scoped to this file and this one
    # message; reported in the 2.2 handoff for a pyproject decision. Remove
    # when pyRdfa stops calling `utcnow()` or pyproject ignores it.
    pytest.mark.filterwarnings("ignore:datetime.datetime.utcnow:DeprecationWarning:pyRdfa"),
]

UA = "SpydraTest/1.0 (+https://spydra.test)"
SKU = "HT-SB-001"
IN_CONTEXT = f"/shop/cutting/blades/p/{SKU}"
CANONICAL = f"/shop/p/{SKU}"
POLISH = "/shop/p/HT-PO-001"


class NoRenderer:
    """Every Halden domain here is static; a render would be a bug."""

    path = FetchPath.RENDERED

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        raise AssertionError(f"sidecar not expected for {request.url}")

    async def aclose(self) -> None:
        pass


@pytest.fixture
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


def build(engine: AsyncEngine, static: HttpxFetcher) -> PageCrawler:
    clock = SystemClock()
    observations = PostgresObservations(engine)
    rendered = NoRenderer()
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
        clock=clock,
        user_agent=UA,
    )


async def make_due(engine: AsyncEngine, domain: DomainId) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.domains SET next_eligible_at = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": int(domain)},
        )


async def crawl_all(engine: AsyncEngine, base: str, paths: list[str]) -> tuple[DomainId, RunId]:
    """Enqueue `paths` on the fixture site's domain in one run, then claim
    and crawl until the queue is empty."""
    domain = await seed_domain(engine, base.removeprefix("http://"))
    run = await seed_run(engine, [int(domain)])
    frontier = PostgresFrontier(engine)
    assert await frontier.enqueue(run, domain, [(base + p, 1) for p in paths]) == len(paths)

    static = HttpxFetcher(SystemClock())
    try:
        crawler = build(engine, static)
        for _ in paths:
            await make_due(engine, domain)
            item = await frontier.claim()
            assert item is not None, "nothing claimable"
            await crawler.crawl(item)
        await make_due(engine, domain)
        assert await frontier.claim() is None, "rows left after crawling every path"
    finally:
        await static.aclose()
    return domain, run


async def pages(engine: AsyncEngine, domain: DomainId) -> dict[str, int]:
    """url → number of observations on that page row."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    """
                    SELECT p.url, count(o.id) AS observations
                    FROM crawl.pages p
                    LEFT JOIN crawl.page_observations o ON o.page_id = p.id
                    WHERE p.domain_id = :d
                    GROUP BY p.url
                    """
                ),
                {"d": int(domain)},
            )
        ).all()
    return {r.url: r.observations for r in rows}


async def queue_states(engine: AsyncEngine, run: RunId) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text("SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r"),
                {"r": int(run)},
            )
        ).all()
    return {r.url: r.state for r in rows}


async def test_a_same_host_canonical_collapses_two_urls_into_one_page_row(
    clean_crawl: AsyncEngine, site: FixtureSite
) -> None:
    base = site.base_url
    domain, run = await crawl_all(clean_crawl, base, [IN_CONTEXT, CANONICAL])

    # Both URLs were fetched: the collapse is in the page row, not by
    # skipping a fetch.
    assert await queue_states(clean_crawl, run) == {
        base + IN_CONTEXT: "done",
        base + CANONICAL: "done",
    }
    assert await pages(clean_crawl, domain) == {base + CANONICAL: 2}


@pytest.mark.parametrize("order", ["context-first", "canonical-first"])
async def test_the_collapse_does_not_depend_on_which_url_is_crawled_first(
    clean_crawl: AsyncEngine, site: FixtureSite, order: str
) -> None:
    base = site.base_url
    paths = [IN_CONTEXT, CANONICAL] if order == "context-first" else [CANONICAL, IN_CONTEXT]
    domain, _ = await crawl_all(clean_crawl, base, paths)

    assert await pages(clean_crawl, domain) == {base + CANONICAL: 2}


async def test_the_in_context_url_alone_is_filed_under_its_canonical(
    clean_crawl: AsyncEngine, site: FixtureSite
) -> None:
    """Even when the canonical URL itself is never crawled: the page row is
    the site's answer, not the link the crawler happened to follow."""
    base = site.base_url
    domain, _ = await crawl_all(clean_crawl, base, [IN_CONTEXT])

    assert await pages(clean_crawl, domain) == {base + CANONICAL: 1}


async def test_an_off_host_canonical_leaves_the_page_under_its_own_url(
    clean_crawl: AsyncEngine, site: FixtureSite
) -> None:
    base = site.base_url
    domain, _ = await crawl_all(clean_crawl, base, [POLISH])

    assert await pages(clean_crawl, domain) == {base + POLISH: 1}


async def test_a_page_with_no_canonical_is_filed_under_its_canonical_queue_url(
    clean_crawl: AsyncEngine, site: FixtureSite
) -> None:
    """A listing names no canonical; its row is the queue URL's canonical
    form, trailing slash and tracking parameter gone."""
    base = site.base_url
    domain, _ = await crawl_all(clean_crawl, base, ["/shop/cutting/discs/?utm_source=n"])

    assert await pages(clean_crawl, domain) == {base + "/shop/cutting/discs": 1}
