"""Observation writes against real Postgres (BUILD_PLAN 1.11, spec 003 §4-5).

**Against real rows, and with the real fixtures.** ADR-0030's threshold is a
join over the observation history; a suite with a hand-written repository
double would be asserting against a story about that history rather than
against the query that has to be right. TESTING.md §1 asks for the same
thing, and `1.8` already pays the price of committed rows.

The two fixtures that carry this slice are `1.4`'s pair:

  `northfield/product-redesigned.html`  200, real content, template resolves
                                        NOTHING, and the page HAS a prior
                                        non-empty observation -> a regression
  `mertens/product-missing.html`        200, nothing resolves, and NO prior
                                        -> reported, never counted

Its README calls the first "the most valuable file here" and the second "its
mirror image". A suite that treated them the same would have tested neither,
so every threshold test below uses both.
"""

import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.domain.entities import Observation, Template
from spydra.domain.enums import DomainEvent, FetchPath, Strategy, UnknownReason
from spydra.domain.health import assess
from spydra.domain.ids import DomainId, PageId, RunId, TemplateId
from spydra.domain.lifecycle import transition
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.extraction.chain import ChainResult
from spydra.extraction.hashing import content_hash
from spydra.observations.writer import CrawledPage, ObservationWriter, WriteOutcome
from tests.adapters.postgres.observation_seed import (
    domain_state,
    observation_rows,
    seed_observation,
    seed_page,
    seed_template,
    unknown_rows,
)
from tests.adapters.postgres.seed import seed_domain, seed_run
from tests.extraction.pages import page, vantage_template

pytestmark = pytest.mark.integration

GOOD = "vantage-abrasives/product.html"
REDESIGNED = "northfield/product-redesigned.html"
SOFT_404 = "mertens/product-missing.html"


# `tests/extraction/pages.py` stamps every fixture fetch with ONE frozen
# `fetched_at`, which is what makes the chain tests deterministic — and it is
# older than any history a test seeds "an hour ago". Taking it as
# `observed_at` made two whole classes of assertion silently wrong: ADR-0030's
# prior lookup is a strict `observed_at <`, so a seeded prior was *later* than
# the observation it was the prior for and no regression was ever counted, and
# `ORDER BY observed_at` returned the two rows of one page in the wrong order.
# Measured as seven failures, not reasoned about.
#
# So the suite stamps its own, monotonically. Real time, not a fake clock: the
# ordering under test is the database's, and the rows have to be orderable the
# way production's are.
_TICKS = itertools.count()


def tick() -> datetime:
    """A timestamp strictly later than the one before it, and than history."""
    return datetime.now(UTC) + timedelta(milliseconds=next(_TICKS))


def chain() -> ExtractionChain:
    """The real chain, in the real order (spec 003 §1)."""
    return ExtractionChain([StructuredStrategy(), SelectorStrategy()])


def writer(engine: AsyncEngine) -> ObservationWriter:
    return ObservationWriter(PostgresObservations(engine), PostgresAssets(engine))


async def crawl(
    engine: AsyncEngine,
    *,
    fixture: str,
    url: str,
    page_id: PageId,
    domain_id: DomainId,
    run_id: RunId,
    template: Template | None,
    status: int = 200,
    observed_at: datetime | None = None,
    degraded: bool = False,
) -> WriteOutcome:
    """One page, through the real chain and the real writer.

    No shortcut around the extraction: the thing under test is what the
    writer does with what the chain produced, and a test that handed it a
    literal would pass against a chain that had stopped extracting.
    """
    fetched = page(fixture, url, status)
    if degraded:
        fetched = replace(fetched, fell_back_from=FetchPath.RENDERED)
    result = await chain().extract(fetched, template)
    return await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=result,
        template=template,
        observed_at=observed_at or tick(),
    )


async def a_domain_with_a_template(
    engine: AsyncEngine, *, host: str = "vantage-abrasives.test"
) -> tuple[DomainId, TemplateId, Template]:
    domain_id = await seed_domain(engine, host=host)
    template_id = await seed_template(engine, domain_id)
    template = replace(vantage_template(), id=template_id, domain_id=domain_id)
    return domain_id, template_id, template


# ---------------------------------------------------------------------------
# Spec 003 §4: the row, and the hash that decides whether it is a full one
# ---------------------------------------------------------------------------


async def test_a_crawled_page_writes_one_row_with_both_strategy_answers(
    clean_crawl: AsyncEngine,
) -> None:
    """The typed core columns are filled and the rest goes to `attributes`
    (spec 001 §1), and `extraction_rung` records the rung that ran."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    outcome = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    (row,) = await observation_rows(engine, page_id)
    assert row.title == "Resin Fibre Disc 115mm P60"
    assert row.price_amount == Decimal("14.7500")
    assert row.price_currency == "GBP"
    assert row.unchanged is False
    assert row.empty_extraction is False
    assert row.strategy == Strategy.SELECTOR.value
    assert row.extraction_rung == Strategy.SELECTOR.value
    assert outcome.unknown_reason is None
    assert outcome.event is None


async def test_re_crawling_an_unchanged_page_writes_a_lightweight_row(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 003 §4: "if the hash matches the previous observation, write a
    lightweight row (`observed_at`, `http_status`, `unchanged = true`)".

    The hash is kept on the lightweight row rather than nulled: without it
    the NEXT run compares against NULL, writes a full row, and "unchanged"
    degrades into "unchanged every other run".
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    first = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        observed_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    second = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    original, lightweight = await observation_rows(engine, page_id)
    assert original.unchanged is False
    assert lightweight.unchanged is True
    assert lightweight.content_hash == original.content_hash
    # The fields are not repeated — that is what makes it lightweight.
    assert lightweight.title is None
    assert first.observation.content_hash == second.observation.content_hash


async def test_an_unchanged_row_is_not_an_empty_extraction(
    clean_crawl: AsyncEngine,
) -> None:
    """The worst bug available in this slice, held down.

    A lightweight row has no fields, and `empty_extraction(200, {})` is
    `True` by definition. Recompute the predicate against that row and every
    stable page on a stable site scores as empty — each with a non-empty
    prior, so each one a *regression* — and an unchanging catalogue halts
    itself as a redesign on its second run. The verdict is inherited with
    the hash it matched.

    Five stable pages, crawled twice, after an earlier run: the domain must
    still be crawling.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/rfd-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        # An earlier run, so this is not a first run and the priors exist.
        await seed_observation(engine, page_id, earlier_run, empty=False)
        for minutes in (5, 0):
            await crawl(
                engine,
                fixture=GOOD,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
                observed_at=datetime.now(UTC) - timedelta(minutes=minutes),
            )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.pages_crawled == 5
    assert health.empty_pages == 0, "a lightweight row is not an empty extraction"
    assert health.regressions == 0
    assert assess(health) is None
    assert await domain_state(engine, domain_id) == "active"


# ---------------------------------------------------------------------------
# ADR-0030: the redesign halts the domain, the soft 404s never do
# ---------------------------------------------------------------------------


async def test_the_redesigned_fixture_trips_broken(clean_crawl: AsyncEngine) -> None:
    """`1.4`'s README: the redesigned page "HAS a prior non-empty observation
    in the test that uses it, so it must ALSO count toward the broken
    threshold".

    Five pages, two redesigned — 40%. The domain halts mid-run, which is
    spec 003 §3's requirement and the difference between catching a redesign
    and reporting one after the whole catalogue has been overwritten.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    events = []

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcome = await crawl(
            engine,
            fixture=REDESIGNED if i < 2 else GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )
        events.append(outcome.event)

    assert DomainEvent.BREAK in events
    assert await domain_state(engine, domain_id) == "broken"
    # Reported as well as counted: every empty page reaches the inbox.
    assert [r.reason for r in await unknown_rows(engine, domain_id)] == [
        UnknownReason.EMPTY_EXTRACTION.value
    ] * 2


async def test_one_redesigned_page_in_five_is_exactly_the_boundary(
    clean_crawl: AsyncEngine,
) -> None:
    """20% is not over 20% (ADR-0030: `> 0.20`), so this domain keeps
    crawling. The pair with the test above is what proves the ratio is read
    at all rather than "any regression halts"."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        await crawl(
            engine,
            fixture=REDESIGNED if i < 1 else GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.regressions, health.pages_crawled) == (1, 5)
    assert await domain_state(engine, domain_id) == "active"


async def test_however_many_soft_404s_there_are_the_domain_keeps_crawling(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0030's reason for existing: "a healthy domain with more than 20%
    dead links halts itself on every run and reports a redesign that never
    happened".

    Ten dead links out of eleven pages — 91% empty, and not one of them a
    regression, because none has a prior. They are all reported.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine, host="mertens.test")
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    # One page with history, so this is not a first run — otherwise the
    # first-run rule would fire and the test would pass for the wrong reason.
    live_url = "https://mertens.test/catalog/live"
    live = await seed_page(engine, domain_id, live_url, template_id=template.id)
    await seed_observation(engine, live, earlier_run, empty=False)
    await crawl(
        engine,
        fixture=GOOD,
        url=live_url,
        page_id=live,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    for i in range(10):
        url = f"https://mertens.test/catalog/gone-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        outcome = await crawl(
            engine,
            fixture=SOFT_404,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )
        assert outcome.event is None
        assert outcome.unknown_reason is UnknownReason.EMPTY_EXTRACTION

    health = await PostgresObservations(engine).health(run_id, domain_id)
    # Anti-vacuity: the pages really were empty. If the predicate had stopped
    # firing, "no regressions" would be true for the wrong reason and this
    # suite would be green against a detector that detects nothing.
    assert health.empty_pages == 10
    assert health.regressions == 0
    assert await domain_state(engine, domain_id) == "active"
    assert len(await unknown_rows(engine, domain_id)) == 10


async def test_a_redesign_is_still_caught_among_the_dead_links(
    clean_crawl: AsyncEngine,
) -> None:
    """The two fixtures in one run, which is the shape a real catalogue has.

    Eight soft 404s dilute nothing: the ratio is over pages crawled, and two
    regressions in ten pages is 20%... which does not trip. Three does.
    Asserted as counts so the arithmetic is visible rather than inferred
    from a state change.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(10):
        url = f"https://vantage-abrasives.test/catalog/mixed-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        if i < 3:
            # Had working extractions, now redesigned: regressions.
            await seed_observation(engine, page_id, earlier_run, empty=False)
            fixture = REDESIGNED
        elif i < 9:
            # Dead links, never extracted: reported, not counted.
            fixture = SOFT_404
        else:
            await seed_observation(engine, page_id, earlier_run, empty=False)
            fixture = GOOD
        await crawl(
            engine,
            fixture=fixture,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.pages_crawled == 10
    assert health.empty_pages == 9
    assert health.regressions == 3
    assert await domain_state(engine, domain_id) == "broken"


@pytest.mark.parametrize(
    ("regressions", "expected_state"),
    [(21, "broken"), (19, "active")],
)
async def test_21_percent_trips_the_query_and_19_does_not(
    clean_crawl: AsyncEngine, regressions: int, expected_state: str
) -> None:
    """BUILD_PLAN 1.11's "21% trips it while 19% does not", through the real
    counting query over 100 real pages.

    The observations are written with the adapter rather than the chain: 100
    page fetches to prove an arithmetic boundary is a slow test that would
    get deleted, and the chain's output is already proven above. What is
    under test here is the query.
    """
    engine = clean_crawl
    observations = PostgresObservations(engine)
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(100):
        url = f"https://vantage-abrasives.test/catalog/bulk-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        empty = i < regressions
        await observations.insert(
            Observation(
                page_id=page_id,
                run_id=run_id,
                template_id=TemplateId(int(template.id)),
                observed_at=datetime.now(UTC),
                http_status=200,
                strategy=None if empty else Strategy.SELECTOR,
                content_hash=content_hash({} if empty else {"title": f"part {i}"}),
                fields={} if empty else {"title": f"part {i}"},
                empty_extraction=empty,
                extraction_rung=None if empty else Strategy.SELECTOR,
            )
        )

    health = await observations.health(run_id, domain_id)
    assert (health.regressions, health.pages_crawled) == (regressions, 100)

    # The writer applies this in every other test; here the rows were
    # inserted directly, so the verdict is applied directly too.
    event = assess(health)
    if event is not None:
        state = await observations.domain_state(domain_id)
        await observations.set_domain_state(domain_id, transition(state, event))
    assert await domain_state(engine, domain_id) == expected_state


# ---------------------------------------------------------------------------
# The first run: "this never worked" has its own destination
# ---------------------------------------------------------------------------


async def test_a_first_run_past_the_threshold_goes_back_to_review(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0030: "a template approved against samples and failing against the
    catalogue" is not a redesign, so it does not go to `broken` — which means
    "this used to work". It goes back through approval.

    This is also the edge that did not exist before this slice: without
    `active -> awaiting_approval`, the accepted ADR's own prescription raises
    `InvalidTransition` here.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/new-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await crawl(
            engine,
            fixture=REDESIGNED if i < 2 else GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.first_run is True
    assert health.regressions == 0, "nothing can have regressed on a first run"
    assert health.empty_pages == 2
    assert await domain_state(engine, domain_id) == "awaiting_approval"


async def test_a_second_run_is_not_a_first_run(clean_crawl: AsyncEngine) -> None:
    """`first_run` is "no observation from any EARLIER run", not "no
    observations at all". Asked while the current run is writing, the second
    reading makes every run the first one — and no domain ever reaches
    `broken`."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    await seed_observation(engine, page_id, earlier_run, empty=False)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    assert (await PostgresObservations(engine).health(run_id, domain_id)).first_run is False


async def test_the_first_observation_of_a_run_does_not_make_it_a_first_run(
    clean_crawl: AsyncEngine,
) -> None:
    """The mirror: a run whose own rows are the only rows IS a first run, and
    the detector must say so before the ratio is read."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    assert (await PostgresObservations(engine).health(run_id, domain_id)).first_run is True


async def test_a_domain_already_broken_is_not_halted_twice(
    clean_crawl: AsyncEngine,
) -> None:
    """The ratio stays over the threshold for every page after the one that
    tripped it, so the verdict repeats. `transition` raises on an edge that
    does not exist (`broken` has no `break`), and a detector that raises
    mid-crawl loses the observations it was writing."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    # Seven pages, every one of them redesigned: the verdict becomes
    # readable on the fifth (`MINIMUM_PAGES_FOR_A_VERDICT`) and then repeats.
    for i in range(7):
        url = f"https://vantage-abrasives.test/catalog/dead-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    # Halted exactly once, on the page that first made five.
    assert [o.halted for o in outcomes] == [False] * 4 + [True, False, False]
    assert [o.event for o in outcomes] == [None] * 4 + [DomainEvent.BREAK] * 3
    assert await domain_state(engine, domain_id) == "broken"


# ---------------------------------------------------------------------------
# Routing: what reaches the review inbox, and what does not
# ---------------------------------------------------------------------------


async def test_a_page_with_no_template_is_a_configuration_gap(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0027 §3: a no-template page's reason is `no_template`, and it is
    excluded from the threshold entirely. Reporting it as an empty
    extraction sends the operator to review a selector that does not
    exist."""
    engine = clean_crawl
    domain_id = await seed_domain(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/about"
    page_id = await seed_page(engine, domain_id, url)

    outcome = await crawl(
        engine,
        fixture=REDESIGNED,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=None,
    )

    assert outcome.unknown_reason is UnknownReason.NO_TEMPLATE
    (row,) = await observation_rows(engine, page_id)
    assert row.empty_extraction is True
    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.regressions == 0
    # "Counted neither as empty nor as crawled-successfully": out of the
    # numerator AND the denominator, or a domain whose crawl is mostly
    # non-product pages dilutes — or, on a first run, trips — its own ratio.
    assert (health.pages_crawled, health.empty_pages) == (0, 0)


async def test_a_404_is_not_an_empty_extraction_and_is_not_reported(
    clean_crawl: AsyncEngine,
) -> None:
    """The status is part of the predicate (ADR-0027). Routing non-200s would
    fill the inbox with every broken link on the site and bury the one page
    that matters."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/removed"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    await seed_observation(engine, page_id, await seed_run(engine, [int(domain_id)]), empty=False)

    outcome = await crawl(
        engine,
        fixture=SOFT_404,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        status=404,
    )

    assert outcome.unknown_reason is None
    (_prior, row) = await observation_rows(engine, page_id)
    assert row.empty_extraction is False
    assert (await PostgresObservations(engine).health(run_id, domain_id)).regressions == 0


async def test_validation_failures_are_recorded_and_never_route(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0027: a failing field is evidence, not control flow.

    A price of "POA" fails the currency rule, the observation is still
    written with everything that did resolve, and the page is NOT sent to
    review — emptiness is the only routing signal.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    fetched = page(GOOD, url)
    extracted = await chain().extract(fetched, template)
    on_application = ChainResult(
        fields={
            **extracted.fields,
            "price": {"amount": None, "currency": None, "raw": "POA"},
        },
        strategy=extracted.strategy,
    )

    outcome = await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=on_application,
        template=template,
    )

    (row,) = await observation_rows(engine, page_id)
    assert row.validation["price"] == {"rule": "currency", "ok": False, "saw": "POA"}
    assert row.title == "Resin Fibre Disc 115mm P60"
    assert row.price_amount is None
    assert row.empty_extraction is False
    assert outcome.unknown_reason is None


# ---------------------------------------------------------------------------
# The two questions one `strategy` column cannot answer (1.7 open question 2)
# ---------------------------------------------------------------------------


async def test_a_degraded_fetch_records_the_fallback_and_keeps_the_rung(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 012 §4 and TESTING.md §2 name `strategy = static_fallback`, so
    that is what `strategy` carries — and `extraction_rung` keeps the answer
    it displaces. Without the second column a render-down run reports zero
    selector and zero structured extractions across the whole crawl."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        degraded=True,
    )

    (row,) = await observation_rows(engine, page_id)
    assert row.strategy == Strategy.STATIC_FALLBACK.value
    assert row.extraction_rung == Strategy.SELECTOR.value


# ---------------------------------------------------------------------------
# ADR-0027: the predicate is read on the FINAL observation of a page
# ---------------------------------------------------------------------------


async def test_a_retry_that_worked_is_not_a_regression(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0027 pins the verdict to the final observation after any `auto`
    fallback. A page whose static attempt was empty and whose rendered
    retry worked has not regressed — and counting the first attempt as well
    would make every AUTO domain look half broken."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    await seed_observation(engine, page_id, earlier_run, empty=False)

    await crawl(
        engine,
        fixture=REDESIGNED,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        observed_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.pages_crawled == 1, "one page, two observations"
    assert health.regressions == 0
    assert await domain_state(engine, domain_id) == "active"


async def test_a_retry_that_failed_is_a_regression(clean_crawl: AsyncEngine) -> None:
    """The mirror of the test above, and the reason it is not vacuous: the
    same two observations in the other order must count."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    await seed_observation(engine, page_id, earlier_run, empty=False)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        observed_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await crawl(
        engine,
        fixture=REDESIGNED,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.pages_crawled, health.regressions) == (1, 1)
    # One page is never a verdict (`MINIMUM_PAGES_FOR_A_VERDICT`), so the
    # domain keeps crawling — what this test is about is that the SECOND
    # observation is the one counted, and the count is asserted directly.
    assert assess(health) is None
    assert await domain_state(engine, domain_id) == "active"


async def test_the_previous_observation_is_looked_up_across_runs(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 003 §4 compares against "the previous observation", which is the
    page's history and not this run's. A per-run lookup makes every page's
    first observation of every run a full row, and nothing is ever
    unchanged."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    first_run = await seed_run(engine, [int(domain_id)])
    second_run = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=first_run,
        template=template,
        observed_at=datetime.now(UTC) - timedelta(days=1),
    )
    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=second_run,
        template=template,
    )

    _, second = await observation_rows(engine, page_id)
    assert second.unchanged is True


async def test_the_page_is_stamped_as_crawled(clean_crawl: AsyncEngine) -> None:
    """`pages.last_crawled_at` in the same transaction as the insert: a page
    whose observation landed and whose stamp did not is a page the next run
    re-crawls as never-seen."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    observed_at = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)

    await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
        observed_at=observed_at,
    )

    async with engine.connect() as conn:
        stamped = (
            await conn.execute(
                sa.text("SELECT last_crawled_at FROM crawl.pages WHERE id = :id"),
                {"id": int(page_id)},
            )
        ).scalar_one()
    assert stamped == observed_at


# ---------------------------------------------------------------------------
# What the first mutation pass found green
# ---------------------------------------------------------------------------


async def test_a_page_whose_only_field_is_an_asset_url_is_not_empty(
    clean_crawl: AsyncEngine,
) -> None:
    """The corner where the hash and the predicate legitimately disagree.

    Spec 003 §4 excludes asset URLs from the hash, so a page whose only
    resolved field is an image URL normalises to nothing. It is **not**
    empty — a field resolved (ADR-0027) — and the predicate, not the hash,
    decides whether the page is evidence of a regression.

    But nothing survives normalisation, so it has **no hash** (spec 003 §4):
    `content_hash` is NULL and a repeat of it is never `unchanged`. A shared
    digest of `{}` would make every image-only page "the same as before"
    from its second crawl, and `page_current` would then skip the row that
    carries its gallery.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/photo-only"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    fetched = page(GOOD, url)

    outcome = await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=ChainResult(
            fields={"images": ["https://cdn.vantage-abrasives.test/a.jpg"]},
            strategy=Strategy.SELECTOR,
        ),
        template=template,
        observed_at=tick(),
    )

    await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=ChainResult(
            fields={"images": ["https://cdn.vantage-abrasives.test/a.jpg"]},
            strategy=Strategy.SELECTOR,
        ),
        template=template,
        observed_at=tick(),
    )

    first, repeat = await observation_rows(engine, page_id)
    assert first.empty_extraction is False
    assert outcome.unknown_reason is None
    assert first.content_hash is None
    assert repeat.content_hash is None
    assert repeat.unchanged is False, "nothing to compare is not 'the same as before'"
    assert repeat.empty_extraction is False


async def test_a_404_with_no_template_is_not_reported_either(
    clean_crawl: AsyncEngine,
) -> None:
    """The case the status guard actually protects.

    A 404 that resolved nothing is not an empty extraction whatever else is
    true, so the earlier 404 test passes with or without the guard. What
    needs the guard is a non-200 on a page with no template: without it,
    every dead link on an unconfigured host becomes a `no_template` row and
    the review inbox is the site's 404 log.
    """
    engine = clean_crawl
    domain_id = await seed_domain(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/gone"
    page_id = await seed_page(engine, domain_id, url)

    outcome = await crawl(
        engine,
        fixture=SOFT_404,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=None,
        status=404,
    )

    assert outcome.unknown_reason is None
    assert await unknown_rows(engine, domain_id) == []


async def test_a_simultaneous_observation_is_not_an_earlier_one(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0030 says "an **earlier** observation", so the comparison is a
    strict `<`.

    Two observations sharing one `observed_at` carry no order between them,
    and `<=` would let an empty observation count its own twin as the proof
    that the page once worked. The conservative reading is the right one
    here: a false `broken` halts a domain and needs a human to clear it
    (ADR-0004), and nothing is lost — the next run's observation is
    unambiguously later.
    """
    engine = clean_crawl
    observations = PostgresObservations(engine)
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    at = datetime.now(UTC)

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/twin-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        # A non-empty observation at EXACTLY the timestamp of the empty one.
        await seed_observation(engine, page_id, earlier_run, empty=False, observed_at=at)
        await observations.insert(
            Observation(
                page_id=page_id,
                run_id=run_id,
                template_id=TemplateId(int(template.id)),
                observed_at=at,
                http_status=200,
                strategy=None,
                content_hash=content_hash({}),
                fields={},
                empty_extraction=True,
            )
        )

    health = await observations.health(run_id, domain_id)
    assert health.empty_pages == 5
    assert health.regressions == 0
    assert assess(health) is None


async def test_one_domains_regressions_do_not_halt_another(
    clean_crawl: AsyncEngine,
) -> None:
    """A run covers many domains (`runs.domain_ids`), and the ratio is
    per-domain.

    Without the `pages.domain_id` filter the counts are the run's, so one
    redesigned site would halt every host in the same run — and the one that
    reports `broken` would be a domain whose own pages all extracted
    perfectly.
    """
    engine = clean_crawl
    healthy_id, _, healthy_template = await a_domain_with_a_template(engine)
    broken_id, _, broken_template = await a_domain_with_a_template(engine, host="northfield.test")
    earlier_run = await seed_run(engine, [int(healthy_id), int(broken_id)])
    run_id = await seed_run(engine, [int(healthy_id), int(broken_id)])

    for domain_id, template, fixture, host in (
        (healthy_id, healthy_template, GOOD, "vantage-abrasives.test"),
        (broken_id, broken_template, REDESIGNED, "northfield.test"),
    ):
        for i in range(5):
            url = f"https://{host}/catalog/item-{i}"
            page_id = await seed_page(engine, domain_id, url, template_id=template.id)
            await seed_observation(engine, page_id, earlier_run, empty=False)
            await crawl(
                engine,
                fixture=fixture,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )

    observations = PostgresObservations(engine)
    assert (await observations.health(run_id, healthy_id)).regressions == 0
    assert (await observations.health(run_id, broken_id)).regressions == 5
    assert (await observations.health(run_id, healthy_id)).pages_crawled == 5
    assert await domain_state(engine, healthy_id) == "active"
    assert await domain_state(engine, broken_id) == "broken"


# ---------------------------------------------------------------------------
# 1.12: the page path enqueues its own images
# ---------------------------------------------------------------------------


async def asset_queue_rows(engine: AsyncEngine) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT observation_id, source_url, position FROM crawl.asset_queue "
                        "ORDER BY observation_id, position"
                    )
                )
            ).all()
        )


async def test_crawling_a_page_enqueues_its_gallery(clean_crawl: AsyncEngine) -> None:
    """ADR-0003 step 1, through the writer rather than through the adapter:
    `1.13` calls `record()` and nothing else, so if the enqueue were the
    caller's job to remember, the symptom would be an empty asset queue
    noticed months later."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    outcome = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    rows = await asset_queue_rows(engine)
    assert outcome.assets_enqueued == 2
    assert [r.source_url for r in rows] == [
        "https://vantage-abrasives.test/img/rfd-115-060-a.jpg",
        "https://vantage-abrasives.test/img/rfd-115-060-b.jpg",
    ]
    assert [r.position for r in rows] == [0, 1]
    assert {r.observation_id for r in rows} == {outcome.observation_id}


async def test_an_unchanged_page_still_enqueues_its_gallery(
    clean_crawl: AsyncEngine,
) -> None:
    """The lightweight row has no fields, and its images still have to be
    linked.

    Asset URLs are excluded from the hash (spec 003 §4), so an `unchanged`
    row can carry a gallery that did change: a re-upload under new URLs.
    Skipping the enqueue would make that change undetectable. `page_current`
    skips `unchanged` rows (ADR-0033), so reconciling this gallery with the
    view is `5.2`'s; raised in `.tasks/fix-1.11-review-findings.md`. The cost
    is a re-fetch of an unchanged gallery every run.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    first = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )
    second = await crawl(
        engine,
        fixture=GOOD,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    assert second.observation.unchanged is True
    assert second.assets_enqueued == 2
    rows = await asset_queue_rows(engine)
    # Two observations, two galleries: the UNIQUE is per observation, so the
    # second run's row is a new row rather than a conflict.
    assert len(rows) == 4
    assert {r.observation_id for r in rows} == {
        first.observation_id,
        second.observation_id,
    }


# ---------------------------------------------------------------------------
# Review of 1.10/1.11. Each test below pins one acceptance line of
# `.tasks/fix-1.11-review-findings.md`, and is written from the spec line it
# names rather than from the fix.
# ---------------------------------------------------------------------------

IMAGE_STUB = "vantage-abrasives/product-image-stub.html"


async def current_rows(
    engine: AsyncEngine, domain_id: DomainId
) -> list[sa.Row[tuple[object, ...]]]:
    """`crawl.page_current` for one domain's pages — what every reader of
    current state sees (spec 001 §1)."""
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        """
                        SELECT c.page_id, c.title, c.price_amount, c.price_currency,
                               c.unchanged
                        FROM crawl.page_current c
                        JOIN crawl.pages p ON p.id = c.page_id
                        WHERE p.domain_id = :dom
                        ORDER BY c.page_id
                        """
                    ),
                    {"dom": int(domain_id)},
                )
            ).all()
        )


async def record_markup(
    engine: AsyncEngine,
    *,
    body: str,
    url: str,
    page_id: PageId,
    domain_id: DomainId,
    run_id: RunId,
    template: Template | None,
) -> WriteOutcome:
    """`crawl()` for markup that is a variation of a fixture rather than a
    file: the real chain and the real writer, with the body swapped."""
    fetched = replace(page(GOOD, url), body=body)
    result = await chain().extract(fetched, template)
    return await writer(engine).record(
        page=CrawledPage(id=page_id, domain_id=domain_id, url=url),
        run_id=run_id,
        fetched=fetched,
        result=result,
        template=template,
        observed_at=tick(),
    )


# --- B1: current state survives a stable page --------------------------------


async def test_a_stable_page_reads_its_full_content_through_page_current(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 001 §1: `page_current` skips `unchanged` rows, "so the newest
    full row IS the current content".

    The second crawl writes the lightweight row (asserted, so the test cannot
    pass because the page happened to be re-written in full). Read naively as
    "the newest row", every stable product would show no title and no price
    from its second run onward — the whole catalogue blank in the UI, with
    the data sitting one row down.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    for _ in range(2):
        await crawl(
            engine,
            fixture=GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
            observed_at=tick(),
        )

    _, lightweight = await observation_rows(engine, page_id)
    assert lightweight.unchanged is True
    (current,) = await current_rows(engine, domain_id)
    assert current.title == "Resin Fibre Disc 115mm P60"
    assert current.price_amount == Decimal("14.7500")
    assert current.price_currency == "GBP"
    assert current.unchanged is False


async def test_a_changed_page_reads_its_new_content_through_page_current(
    clean_crawl: AsyncEngine,
) -> None:
    """The other half of the same rule. Skipping `unchanged` rows must not
    pin current state to the FIRST full row: a price change is a new full
    row, and it is current — including after it, too, has been re-crawled
    unchanged. Two pages, so "exactly one row per page" is asserted across
    pages and not merely for one.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    original = page(GOOD, "https://vantage-abrasives.test/catalog/x").body
    repriced = original.replace("£14.75", "£15.25")
    assert repriced != original

    pages = []
    for i in range(2):
        url = f"https://vantage-abrasives.test/catalog/rfd-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        pages.append(page_id)
        for body in (original, original, repriced, repriced):
            await record_markup(
                engine,
                body=body,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )

    rows = await observation_rows(engine, pages[0])
    assert [r.unchanged for r in rows] == [False, True, False, True]
    current = await current_rows(engine, domain_id)
    assert [r.page_id for r in current] == pages, "exactly one current row per page"
    assert {r.price_amount for r in current} == {Decimal("15.2500")}
    assert {r.title for r in current} == {"Resin Fibre Disc 115mm P60"}


# --- B2: no-template pages are outside the threshold --------------------------


async def test_no_template_pages_on_a_first_run_do_not_move_the_domain(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0027 §3: a page with no matching template is "counted neither as
    empty nor as crawled-successfully".

    Six of them on a first run — every one empty on a 200, enough to clear
    the minimum sample on their own. Counted, that is a first run 100%
    empty and the domain goes back to review for a template that was never
    asked to match those pages.
    """
    engine = clean_crawl
    domain_id, _, _ = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    for i in range(6):
        url = f"https://vantage-abrasives.test/info/page-{i}"
        page_id = await seed_page(engine, domain_id, url)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=None,
            )
        )

    # Anti-vacuity: these really were reported as configuration gaps.
    assert {o.unknown_reason for o in outcomes} == {UnknownReason.NO_TEMPLATE}
    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert health.first_run is True
    assert (health.pages_crawled, health.empty_pages) == (0, 0)
    assert [o.event for o in outcomes] == [None] * 6
    assert await domain_state(engine, domain_id) == "active"


async def test_no_template_pages_do_not_dilute_the_denominator(
    clean_crawl: AsyncEngine,
) -> None:
    """The same exclusion from the other side: out of `pages_crawled` too.

    Five product pages with priors, two of them redesigned — 40%, a redesign.
    Add eight no-template pages and, counted, the ratio is 2/13 = 15% and the
    redesign goes uncaught. The verdict must be the product pages' alone.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    # The no-template pages first, so a domain that had already been read
    # as diluted would have to un-dilute itself to be caught.
    for i in range(8):
        url = f"https://vantage-abrasives.test/info/page-{i}"
        page_id = await seed_page(engine, domain_id, url)
        await crawl(
            engine,
            fixture=GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=None,
        )
    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        await crawl(
            engine,
            fixture=REDESIGNED if i < 2 else GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.pages_crawled, health.regressions) == (5, 2)
    assert await domain_state(engine, domain_id) == "broken"


# --- B3: an image-only stub, through the chain and into the row ---------------


async def test_an_image_only_stub_with_a_template_writes_the_templates_fields(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 003 §1, end to end: a `schema.org/Product` carrying only a share
    image must not stop the chain above the approved template. What lands in
    the row — and so in `page_current` — is the template's title and price.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    await crawl(
        engine,
        fixture=IMAGE_STUB,
        url=url,
        page_id=page_id,
        domain_id=domain_id,
        run_id=run_id,
        template=template,
    )

    (row,) = await observation_rows(engine, page_id)
    assert row.strategy == Strategy.SELECTOR.value
    assert row.title == "Resin Fibre Disc 115mm P60"
    assert row.price_amount == Decimal("14.7500")
    assert row.price_currency == "GBP"
    assert row.content_hash is not None


async def test_an_image_only_stub_has_no_hash_and_is_never_unchanged(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 003 §4: when nothing survives normalisation "there is **no
    hash** ... and the row is never `unchanged`".

    With no template the stub's image is all there is: the row is written
    from rung 1, is not an empty extraction (a field resolved), and has
    nothing to compare. Crawled twice, the second row must be a full row —
    read as "unchanged", it would be skipped by `page_current` and its
    gallery attached to a row nobody reads.
    """
    engine = clean_crawl
    domain_id, _, _ = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url)

    for _ in range(2):
        await crawl(
            engine,
            fixture=IMAGE_STUB,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=None,
        )

    first, second = await observation_rows(engine, page_id)
    assert first.strategy == Strategy.STRUCTURED.value
    assert first.empty_extraction is False
    assert (first.content_hash, second.content_hash) == (None, None)
    assert second.unchanged is False


async def test_a_row_is_never_both_unchanged_and_empty(clean_crawl: AsyncEngine) -> None:
    """The two flags are contradictory: `unchanged` says "the same content as
    before", `empty_extraction` says "there was no content". A page that is
    empty twice — the redesigned fixture and the soft 404, each crawled on
    two runs — has nothing to be the same AS, so its second row is a full,
    empty row and never a lightweight one. Read the other way, a redesign
    that persists across runs would vanish from `page_current`'s view of
    the page's history as "unchanged".
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    runs = [await seed_run(engine, [int(domain_id)]) for _ in range(2)]

    for fixture in (REDESIGNED, SOFT_404):
        url = f"https://vantage-abrasives.test/catalog/{fixture.split('/')[0]}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        for run_id in runs:
            await crawl(
                engine,
                fixture=fixture,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        rows = await observation_rows(engine, page_id)
        assert [r.empty_extraction for r in rows] == [True, True], fixture
        assert [r.unchanged for r in rows] == [False, False], fixture
        assert [r.content_hash for r in rows] == [None, None], fixture


# --- 4: one open inbox row per page -------------------------------------------


async def inbox_rows(engine: AsyncEngine, domain_id: DomainId) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        """
                        SELECT id, url, reason, resolved_at FROM crawl.unknown_pages
                        WHERE domain_id = :dom ORDER BY id
                        """
                    ),
                    {"dom": int(domain_id)},
                )
            ).all()
        )


async def test_a_page_empty_on_every_run_is_one_open_inbox_item(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 001 §1: `unknown_pages` is the review inbox, and an inbox item is
    a page to look at — not a page per run. A dead link crawled nightly would
    otherwise add a row a night, and a large catalogue's handful of dead
    links becomes an inbox nobody can read.

    Resolving it closes the item; the page going empty AGAIN after that is
    new information and opens a new one.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine, host="mertens.test")
    url = "https://mertens.test/catalog/discontinued-item"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)

    async def a_run() -> WriteOutcome:
        return await crawl(
            engine,
            fixture=SOFT_404,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=await seed_run(engine, [int(domain_id)]),
            template=template,
        )

    # The reason is reported on both runs; only the first opens an item.
    opened = []
    for _ in range(2):
        outcome = await a_run()
        assert outcome.unknown_reason is UnknownReason.EMPTY_EXTRACTION
        opened.append(outcome.inbox_opened)
    assert opened == [True, False]

    (only,) = await inbox_rows(engine, domain_id)
    assert only.resolved_at is None
    assert only.reason == UnknownReason.EMPTY_EXTRACTION.value

    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.unknown_pages SET resolved_at = now() WHERE id = :id"),
            {"id": only.id},
        )
    assert (await a_run()).inbox_opened is True

    resolved, reopened = await inbox_rows(engine, domain_id)
    assert resolved.id == only.id and resolved.resolved_at is not None
    assert reopened.url == url and reopened.resolved_at is None


# --- 5: the verdict is reached on the page that crosses the threshold ---------


async def test_the_page_that_completes_the_minimum_sample_can_halt_the_domain(
    clean_crawl: AsyncEngine,
) -> None:
    """Spec 003 §3: past the threshold, crawling "stops for it mid-run".

    Four redesigned pages are too few for a verdict. The fifth page EXTRACTS
    — and it is the page that makes the sample big enough, at which point
    the run reads 4/5 = 80% regressions. A detector that only re-reads the
    ratio when the current page is empty would let this domain carry on
    until its next empty page, however long that took.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED if i < 4 else GOOD,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    assert [o.event for o in outcomes] == [None] * 4 + [DomainEvent.BREAK]
    assert [o.halted for o in outcomes] == [False] * 4 + [True]
    assert await domain_state(engine, domain_id) == "broken"


async def test_on_a_first_run_the_fifth_page_can_send_the_domain_back(
    clean_crawl: AsyncEngine,
) -> None:
    """The first-run mirror of the test above (ADR-0030): four pages that
    never extracted, then one that does. 4/5 empty on a first run is a
    template that never worked, and the verdict is due on page five."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/new-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED if i < 4 else GOOD,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    assert [o.event for o in outcomes] == [None] * 4 + [DomainEvent.NEVER_MATCHED]
    assert outcomes[-1].halted is True
    assert await domain_state(engine, domain_id) == "awaiting_approval"


async def test_no_template_pages_do_not_count_toward_the_minimum_sample(
    clean_crawl: AsyncEngine,
) -> None:
    """ADR-0027 §3's exclusion applies to the minimum sample as much as to
    the ratio. Six no-template pages, then four redesigned product pages,
    then one that extracts: the product pages reach five on the last page,
    and that page is where 4/5 regressions becomes a verdict. Counting the
    no-template pages toward "enough pages yet?" would declare the sample
    complete long before it is, and the extracting page would be waved
    through unassessed.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])

    for i in range(6):
        url = f"https://vantage-abrasives.test/info/page-{i}"
        page_id = await seed_page(engine, domain_id, url)
        await crawl(
            engine,
            fixture=GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=None,
        )
    outcomes = []
    for i in range(5):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED if i < 4 else GOOD,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    assert [o.event for o in outcomes] == [None] * 4 + [DomainEvent.BREAK]
    assert await domain_state(engine, domain_id) == "broken"


async def test_past_the_minimum_the_page_that_crosses_the_threshold_halts(
    clean_crawl: AsyncEngine,
) -> None:
    """Mid-run, past the minimum sample: five good pages, then redesigned
    ones. The sixth page is 1/6 regressions (under a fifth); the seventh is
    2/7 (over). The halt belongs to the seventh page and to no earlier one.
    """
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    for i in range(7):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcomes.append(
            await crawl(
                engine,
                fixture=GOOD if i < 5 else REDESIGNED,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    assert [o.event for o in outcomes] == [None] * 6 + [DomainEvent.BREAK]
    assert [o.halted for o in outcomes] == [False] * 6 + [True]


async def test_past_the_minimum_pages_that_extract_never_move_the_domain(
    clean_crawl: AsyncEngine,
) -> None:
    """The other side of the boundary: a domain sitting exactly at it — one
    regression in five, which is not over a fifth — followed by pages that
    extract. Each of them can only lower the ratio, so none of them may
    produce an event."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    earlier_run = await seed_run(engine, [int(domain_id)])
    run_id = await seed_run(engine, [int(domain_id)])
    outcomes = []

    for i in range(10):
        url = f"https://vantage-abrasives.test/catalog/part-{i}"
        page_id = await seed_page(engine, domain_id, url, template_id=template.id)
        await seed_observation(engine, page_id, earlier_run, empty=False)
        outcomes.append(
            await crawl(
                engine,
                fixture=REDESIGNED if i == 0 else GOOD,
                url=url,
                page_id=page_id,
                domain_id=domain_id,
                run_id=run_id,
                template=template,
            )
        )

    health = await PostgresObservations(engine).health(run_id, domain_id)
    assert (health.regressions, health.pages_crawled) == (1, 10)
    assert [o.event for o in outcomes] == [None] * 10
    assert await domain_state(engine, domain_id) == "active"


# --- 6a: the crawl stamp only moves forward -----------------------------------


async def test_an_older_observation_does_not_move_last_crawled_at_backwards(
    clean_crawl: AsyncEngine,
) -> None:
    """`pages.last_crawled_at` is when the page was last seen (spec 001 §1),
    and it is what recency is read from now that `page_current` skips
    lightweight rows. Observations can land out of order — a retry, a slow
    worker finishing after a faster one — and an older write that overwrote
    the stamp would make a fresh page look stale and be re-crawled early."""
    engine = clean_crawl
    domain_id, _, template = await a_domain_with_a_template(engine)
    run_id = await seed_run(engine, [int(domain_id)])
    url = "https://vantage-abrasives.test/catalog/rfd-115-060"
    page_id = await seed_page(engine, domain_id, url, template_id=template.id)
    newer = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    older = newer - timedelta(hours=1)

    for at in (newer, older):
        await crawl(
            engine,
            fixture=GOOD,
            url=url,
            page_id=page_id,
            domain_id=domain_id,
            run_id=run_id,
            template=template,
            observed_at=at,
        )

    async with engine.connect() as conn:
        stamped = (
            await conn.execute(
                sa.text("SELECT last_crawled_at FROM crawl.pages WHERE id = :id"),
                {"id": int(page_id)},
            )
        ).scalar_one()
    assert stamped == newer
