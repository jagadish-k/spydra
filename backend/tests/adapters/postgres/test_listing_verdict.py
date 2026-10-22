"""A listing template's page is never an extraction verdict (ADR-0039).

Phase 2 crawls from category seeds, and a category page is matched by a
`listing` template that carries discovery rules and, normally, no fields.
Before ADR-0039 every such page was an empty extraction: an inbox row each,
and on a first run a domain whose listings outnumbered its products went
back to review for a template that was working.

**Both sides, as `test_observations.py` does for the no-template pages.**
Excluded from the inbox; out of the numerator AND the denominator; out of
the minimum sample; and a listing write is not itself assessed. Each of
those is a separate place the exclusion can be missing, so each has its own
test. And the contrast, which is what makes the rest mean anything: an
empty PRODUCT page is still reported and still counts.

The listing pages are Halden's (`catalogue.render`), the real markup the
template is written against, read without a server: what is under test is
the writer, not the fetch.
"""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.domain.entities import DiscoveryRules, FieldRule, Template
from spydra.domain.enums import (
    DomainEvent,
    FetchPath,
    PageKind,
    ProposedBy,
    UnknownReason,
)
from spydra.domain.fetch import FetchedPage
from spydra.domain.ids import DomainId, PageId, RunId, TemplateId
from spydra.observations.writer import CrawledPage, WriteOutcome
from tests.adapters.postgres.observation_seed import (
    domain_state,
    observation_rows,
    seed_observation,
    seed_page,
    unknown_rows,
)
from tests.adapters.postgres.seed import seed_run
from tests.adapters.postgres.test_observations import (
    GOOD,
    REDESIGNED,
    a_domain_with_a_template,
    chain,
    crawl,
    tick,
    writer,
)
from tests.fixtures import catalogue

pytestmark = pytest.mark.integration

HOST = "vantage-abrasives.test"
LISTINGS = (
    "/shop/cutting/",
    "/shop/cutting/discs/",
    "/shop/cutting/discs/?page=2",
    "/shop/cutting/discs/?page=3",
    "/shop/cutting/blades/",
    "/shop/grinding/",
    "/shop/grinding/wheels/",
    "/shop/grinding/belts/",
    "/shop/grinding/belts/narrow/",
    "/shop/grinding/belts/wide/",
)


async def seed_listing_template(
    engine: AsyncEngine, domain_id: DomainId, *, fields: bool = False
) -> Template:
    """A `listing` template row, and the entity the writer is handed. The
    row matters as much as the entity: the health SQL reads `page_kind`
    from `crawl.templates`, the writer from the entity."""
    async with engine.begin() as conn:
        template_id = TemplateId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.templates
                            (domain_id, name, url_pattern, page_kind, version,
                             is_active, approved_at)
                        VALUES (:dom, 'halden listing', '^/shop/', 'listing', 1, true, now())
                        RETURNING id
                        """
                    ),
                    {"dom": int(domain_id)},
                )
            ).scalar_one()
        )
    return Template(
        id=template_id,
        domain_id=domain_id,
        name="halden listing",
        url_pattern="^/shop/",
        page_kind=PageKind.LISTING,
        version=1,
        is_active=True,
        discovery=DiscoveryRules(product_links="a.product-card__link", next_page="a[rel='next']"),
        # A heading is something; with it, a listing page is NOT empty, which
        # is what a dilution test needs.
        extraction={"heading": FieldRule(selector=".listing__title")} if fields else {},
        proposed_by=ProposedBy.HUMAN,
    )


async def seed_listing_page(engine: AsyncEngine, domain_id: DomainId, url: str) -> PageId:
    async with engine.begin() as conn:
        return PageId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.pages (domain_id, url, url_hash, page_kind)
                        VALUES (:dom, :url, :hash, 'listing')
                        RETURNING id
                        """
                    ),
                    {"dom": int(domain_id), "url": url, "hash": url_hash(url)},
                )
            ).scalar_one()
        )


def halden(path_and_query: str, url: str) -> FetchedPage:
    path, _, query = path_and_query.partition("?")
    rendered = catalogue.render(path, query, catalogue.HOST)
    assert rendered is not None and rendered[0] == 200, path_and_query
    return FetchedPage(
        request_url=url,
        final_url=url,
        http_status=200,
        body=rendered[1].decode(),
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=40,
        fetch_path=FetchPath.STATIC,
    )


async def record_listing(
    engine: AsyncEngine,
    domain_id: DomainId,
    run_id: RunId,
    template: Template,
    path: str,
) -> tuple[PageId, WriteOutcome]:
    url = f"https://{HOST}{path}"
    page_id = await seed_listing_page(engine, domain_id, url)
    fetched = halden(path, url)
    result = await chain().extract(fetched, template)
    outcome = await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=result,
        template=template,
        observed_at=tick(),
    )
    return page_id, outcome


async def record_product(
    engine: AsyncEngine,
    domain_id: DomainId,
    run_id: RunId,
    template: Template,
    n: int,
    *,
    fixture: str,
    prior_run: RunId | None = None,
) -> WriteOutcome:
    url = f"https://{HOST}/catalog/part-{n}"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    if prior_run is not None:
        await seed_observation(engine, page_id, prior_run, empty=False)
    return await crawl(
        engine,
        fixture=fixture,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        observed_at=tick(),
    )


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


async def test_a_listing_page_with_no_fields_opens_no_inbox_row_and_is_not_counted(
    clean_crawl: AsyncEngine,
) -> None:
    engine = clean_crawl
    domain_id, _, _ = await a_domain_with_a_template(engine, host=HOST)
    listing = await seed_listing_template(engine, domain_id)
    run_id = await seed_run(engine, [int(domain_id)])

    page_id, outcome = await record_listing(engine, domain_id, run_id, listing, "/shop/cutting/")

    assert outcome.unknown_reason is None
    assert outcome.inbox_opened is False
    assert await unknown_rows(engine, domain_id) == []
    # Still observed: append-only history is not skipped for a listing.
    assert len(await observation_rows(engine, page_id)) == 1
    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.pages_crawled, health.empty_pages, health.regressions) == (0, 0, 0)


async def test_an_empty_product_page_is_still_reported_and_counted(
    clean_crawl: AsyncEngine,
) -> None:
    """The contrast. Without it, a writer that had stopped reporting empty
    pages altogether would pass the test above."""
    engine = clean_crawl
    domain_id, _, product = await a_domain_with_a_template(engine, host=HOST)
    await seed_listing_template(engine, domain_id)
    run_id = await seed_run(engine, [int(domain_id)])

    outcome = await record_product(engine, domain_id, run_id, product, 0, fixture=REDESIGNED)

    assert outcome.unknown_reason is UnknownReason.EMPTY_EXTRACTION
    assert [r.reason for r in await unknown_rows(engine, domain_id)] == ["empty_extraction"]
    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.pages_crawled, health.empty_pages) == (1, 1)


# ---------------------------------------------------------------------------
# The threshold (ADR-0030's counts)
# ---------------------------------------------------------------------------


async def test_a_first_category_crawl_of_empty_listings_does_not_move_the_domain(
    clean_crawl: AsyncEngine,
) -> None:
    """The case ADR-0039 was found on: a first run from a category seed,
    ten listing pages (all empty) and five products that extract. Counted,
    that is 10/15 empty on a first run and the domain goes back to review."""
    engine = clean_crawl
    domain_id, _, product = await a_domain_with_a_template(engine, host=HOST)
    listing = await seed_listing_template(engine, domain_id)
    run_id = await seed_run(engine, [int(domain_id)])

    listing_outcomes = [
        (await record_listing(engine, domain_id, run_id, listing, p))[1] for p in LISTINGS
    ]
    product_outcomes = [
        await record_product(engine, domain_id, run_id, product, n, fixture=GOOD) for n in range(5)
    ]

    # Anti-vacuity: the listings really were empty observations.
    assert all(o.observation.empty_extraction for o in listing_outcomes)
    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.first_run is True
    assert (health.pages_crawled, health.empty_pages) == (5, 0)
    assert [o.event for o in listing_outcomes + product_outcomes] == [None] * 15
    assert await domain_state(engine, domain_id) == "active"
    assert await unknown_rows(engine, domain_id) == []


async def test_listing_pages_that_extract_do_not_dilute_a_redesign(
    clean_crawl: AsyncEngine,
) -> None:
    """The other side: out of the denominator too. Five product pages with
    priors, two redesigned, is 40%. Eight listing pages that DID extract
    something (a heading), counted, make it 2/13 and the redesign is
    missed."""
    engine = clean_crawl
    domain_id, _, product = await a_domain_with_a_template(engine, host=HOST)
    listing = await seed_listing_template(engine, domain_id, fields=True)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    # Listings first, so a diluted reading would have to un-dilute itself.
    for path in LISTINGS[:8]:
        _, outcome = await record_listing(engine, domain_id, run_id, listing, path)
        assert outcome.observation.empty_extraction is False, "the heading did not extract"
    for n in range(5):
        await record_product(
            engine,
            domain_id,
            run_id,
            product,
            n,
            fixture=REDESIGNED if n < 2 else GOOD,
            prior_run=earlier_run,
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.pages_crawled, health.regressions) == (5, 2)
    assert await domain_state(engine, domain_id) == "broken"


async def test_listing_pages_do_not_count_toward_the_minimum_sample(
    clean_crawl: AsyncEngine,
) -> None:
    """Six listings, four redesigned products, then one that extracts. The
    fifth PRODUCT is the one that makes the sample big enough, and 4/5 is a
    verdict. Counting listings toward the minimum, the run is already past
    it, the non-empty fifth page is not assessed, and the redesign carries
    on until the next empty page."""
    engine = clean_crawl
    domain_id, _, product = await a_domain_with_a_template(engine, host=HOST)
    listing = await seed_listing_template(engine, domain_id)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for path in LISTINGS[:6]:
        await record_listing(engine, domain_id, run_id, listing, path)
    outcomes = [
        await record_product(
            engine,
            domain_id,
            run_id,
            product,
            n,
            fixture=REDESIGNED if n < 4 else GOOD,
            prior_run=earlier_run,
        )
        for n in range(5)
    ]

    assert [o.event for o in outcomes] == [None] * 4 + [DomainEvent.BREAK]
    assert outcomes[-1].halted is True
    assert await domain_state(engine, domain_id) == "broken"


async def test_a_listing_write_is_not_itself_a_verdict(clean_crawl: AsyncEngine) -> None:
    """ADR-0039: a listing page "cannot change the verdict and is not
    assessed". After a redesign has broken the domain, an empty listing
    page reports no event of its own; reporting one would put a listing
    page's URL on a `broken` verdict it had no part in."""
    engine = clean_crawl
    domain_id, _, product = await a_domain_with_a_template(engine, host=HOST)
    listing = await seed_listing_template(engine, domain_id)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    for n in range(5):
        await record_product(
            engine, domain_id, run_id, product, n, fixture=REDESIGNED, prior_run=earlier_run
        )
    assert await domain_state(engine, domain_id) == "broken"

    _, outcome = await record_listing(engine, domain_id, run_id, listing, "/shop/cutting/")

    assert (outcome.event, outcome.halted) == (None, False)
