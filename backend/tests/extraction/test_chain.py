"""The extraction chain against `1.4`'s fixtures (spec 003 §5, BUILD_PLAN 1.10).

The fixtures are the real files. `orbis-components/product-jsonld.html` and
`product-stripped.html` are the same page but for the JSON-LD block — `1.4`
generates them from one source precisely so this pair cannot drift, because
**the pair is the test**: rung 1 must win on the first and rung 2 on the
second, and a test that passed on one and failed on the other has found a
chain-ordering bug and nothing else.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from spydra.domain.entities import (
    FieldRule,
    Rule,
)
from spydra.domain.enums import (
    FetchPath,
    RuleName,
    Strategy,
)
from spydra.domain.fetch import FetchedPage
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.extraction.validation import empty_extraction, validate
from tests.extraction.pages import PAGES, page, vantage_template  # noqa: E402


def chain(domain_currency: str | None = None) -> ExtractionChain:
    """The real order: structured, then selector. Rung 3 is absent on purpose
    — ADR-0005 forbids the model at crawl time."""
    return ExtractionChain([StructuredStrategy(), SelectorStrategy(domain_currency)])


# ---------------------------------------------------------------------------
# Spec 003 §5, first two lines — the pair that IS the test
# ---------------------------------------------------------------------------


async def test_a_jsonld_page_extracts_via_structured_without_a_template() -> None:
    """Spec 003 §5: "without consulting a template". Passing `None` is how
    that is asserted — a rung 1 that needed one would raise or return
    nothing, and the whole value of structured data is that it works before
    anyone has written a selector."""
    result = await chain().extract(
        page("orbis-components/product-jsonld.html", "https://orbis.test/components/fh-520-pm"),
        template=None,
    )

    assert result.strategy is Strategy.STRUCTURED
    assert result.fields["title"] == "Panel Mount Fuse Holder 5x20mm"
    # The SAME composite shape the selector rung emits — one shape, one
    # currency rule, one thing for `1.11` to split into the two columns.
    assert result.fields["price"] == {
        "amount": Decimal("3.40"),
        "currency": "GBP",
        "raw": "3.40",
    }
    assert result.fields["sku"] == "OC-FH-520-PM"
    assert result.fields["vendor"] == "Orbis Components"
    # The bare token, not the schema.org URL — a column of URLs is one
    # nobody can scan.
    assert result.fields["availability"] == "InStock"
    assert result.fields["images"] == [
        "https://orbis.test/img/fh-520-pm-a.jpg",
        "https://orbis.test/img/fh-520-pm-b.jpg",
    ]


async def test_the_same_page_without_its_jsonld_falls_through_to_the_selector() -> None:
    """The other half. `1.4` generates the twins from one source so the only
    difference is the JSON-LD block, which is what makes this a test of
    chain ORDER rather than of two unrelated pages.

    Note this needs no template either — rung 1 declines, rung 2 declines
    without one, and the chain reports `unknown`, which is the third thing
    the pair proves."""
    stripped = page(
        "orbis-components/product-stripped.html", "https://orbis.test/components/fh-520-pm-nold"
    )
    without_template = await chain().extract(stripped, template=None)
    assert without_template.strategy is None, "no rung can work without JSON-LD or a template"
    assert without_template.empty is True


async def test_the_selector_rung_extracts_the_well_formed_fixture() -> None:
    result = await chain("GBP").extract(
        page("vantage-abrasives/product.html", "https://vantage-abrasives.test/catalog/x"),
        template=vantage_template(),
    )

    assert result.strategy is Strategy.SELECTOR
    assert result.fields["title"] == "Resin Fibre Disc 115mm P60"
    assert result.fields["price"] == {
        "amount": Decimal("14.75"),
        "currency": "GBP",
        # The raw text travels with the parsed value so a failure can report
        # what it SAW — spec 003 §3's example record is `"saw": "POA"`.
        "raw": "£14.75",
    }
    assert result.fields["availability"] == "In stock"
    assert result.fields["images"] == [
        "https://vantage-abrasives.test/img/rfd-115-060-a.jpg",
        "https://vantage-abrasives.test/img/rfd-115-060-b.jpg",
    ]


BOTH_RUNGS_HTML = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"From JSON-LD",
 "offers":{"@type":"Offer","price":"1.00","priceCurrency":"GBP"}}
</script></head><body><main class="product">
<h1 class="product__title">From the selector</h1>
<div class="product__price">£2.00</div>
<div class="gallery"><img class="gallery__image" src="/a.jpg"/></div>
</main></body></html>"""


async def test_structured_wins_over_the_selector_when_both_could_work() -> None:
    """Ordering, asserted on a page where **both rungs would succeed**.

    The first version of this test used the orbis JSON-LD fixture with the
    vantage template — and that template's selectors match nothing on that
    page, so rung 2 produced an empty extraction and the chain ended at rung
    1 whichever order it tried them in. Mutation found it: reversing the
    chain left the whole suite green.

    So the page below carries both, with **different values**, and the
    assertion is on which value came back. Spec 003 §1: structured data "is
    more stable than CSS selectors, survives redesigns and needs no model",
    so a chain that consulted the template first would throw that away on
    every page that has both.
    """
    both = FetchedPage(
        request_url="https://x.test/p",
        final_url="https://x.test/p",
        http_status=200,
        body=BOTH_RUNGS_HTML,
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=10,
        fetch_path=FetchPath.STATIC,
    )

    result = await chain("GBP").extract(both, template=vantage_template())

    assert result.strategy is Strategy.STRUCTURED
    assert result.fields["title"] == "From JSON-LD", "the selector rung won, so the order is wrong"


# ---------------------------------------------------------------------------
# The redesign and the soft 404 — ADR-0030's pair
# ---------------------------------------------------------------------------


async def test_the_redesigned_page_yields_an_empty_extraction() -> None:
    """TESTING.md §4 calls this "the most valuable file in the suite": a 200
    whose selectors resolve to nothing. It is the failure that produces no
    error — and with nothing `required` (ADR-0027) it is `empty_extraction`
    that has to fire on it."""
    result = await chain("GBP").extract(
        page("northfield/product-redesigned.html", "https://northfield.test/fixings/m8x40"),
        template=vantage_template(),
    )

    assert empty_extraction(200, result.fields) is True
    assert result.empty is True, "the chain reports unknown rather than a half-page"


async def test_the_soft_404_also_yields_an_empty_extraction() -> None:
    """ADR-0030's mirror image. Also a 200 with nothing resolving — and the
    predicate CANNOT tell it apart from a redesign, which is the point: the
    difference is the prior observation, and that is `1.11`'s job. If this
    predicate tried to distinguish them it would be guessing from content."""
    result = await chain("GBP").extract(
        page("mertens/product-missing.html", "https://mertens.test/katalog/discontinued"),
        template=vantage_template(),
    )
    assert empty_extraction(200, result.fields) is True


async def test_a_non_200_with_nothing_resolving_is_not_an_empty_extraction() -> None:
    """ADR-0027's predicate includes the status for a reason. A 404 that
    yielded nothing is a 404 — counting it would make every dead link
    evidence of a redesign and push a healthy domain past the 20% threshold
    on a catalogue with ordinary rot."""
    assert empty_extraction(404, {"title": None, "price": None}) is False
    assert empty_extraction(500, {}) is False
    assert empty_extraction(200, {"title": None, "price": None}) is True


async def test_a_single_resolved_field_is_not_an_empty_extraction() -> None:
    """ "No field resolved to a non-empty value" — so one that did is enough.
    A predicate using `any` instead of `all` would fire on every page with a
    single broken selector and halt healthy domains wholesale."""
    assert empty_extraction(200, {"title": "Still here", "price": None}) is False
    assert empty_extraction(200, {"title": "", "price": None, "images": []}) is True
    # A genuine zero is data, not emptiness.
    assert empty_extraction(200, {"stock": 0}) is False
    assert empty_extraction(200, {"price": Decimal("0")}) is False


# ---------------------------------------------------------------------------
# ADR-0027 — validation records and never routes
# ---------------------------------------------------------------------------


async def test_a_price_of_poa_is_a_validation_failure_not_zero() -> None:
    """Spec 003 §5 names this case, and spec 003 §3's example record is
    literally `{"rule": "currency", "ok": false, "saw": "POA"}`.

    The observation is still written, with everything else that resolved —
    ADR-0027: "partial data is never discarded"."""
    template = vantage_template()
    html = (PAGES / "vantage-abrasives/product.html").read_text().replace("£14.75", "POA")
    poa = FetchedPage(
        request_url="https://vantage-abrasives.test/catalog/x",
        final_url="https://vantage-abrasives.test/catalog/x",
        http_status=200,
        body=html,
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=40,
        fetch_path=FetchPath.STATIC,
    )

    result = await chain("GBP").extract(poa, template=template)
    failures = validate(result.fields, template.extraction)

    assert "price" in failures, "POA must be recorded as a failure"
    assert failures["price"].rule is RuleName.CURRENCY
    assert failures["price"].ok is False
    # EXACT, not `in`. The first version asserted `"POA" in saw`, which passes
    # against a `saw` of `{'amount': None, 'currency': 'GBP', 'raw': 'POA'}` —
    # the whole repr contains the substring. Mutation found it: dropping the
    # `raw` lookup left the suite green. Spec 003 §3's example record is
    # `"saw": "POA"`, and the repr explains nothing to an operator.
    assert failures["price"].saw == "POA"

    # ...and the rest of the page survived. This is the half ADR-0027 is
    # about: a failing field is evidence, not control flow.
    assert result.fields["title"] == "Resin Fibre Disc 115mm P60"
    assert result.strategy is Strategy.SELECTOR
    assert empty_extraction(200, result.fields) is False, "one bad field is not an empty page"


async def test_validation_records_only_failures() -> None:
    """`page_observations.validation` is what an operator reads to find a
    broken selector. A map containing every field that passed would bury the
    one that did not."""
    template = vantage_template()
    result = await chain("GBP").extract(
        page("vantage-abrasives/product.html", "https://vantage-abrasives.test/catalog/x"),
        template=template,
    )
    assert validate(result.fields, template.extraction) == {}


async def test_no_template_is_not_the_same_as_an_empty_extraction() -> None:
    """ADR-0027 §3: pages with no matching template are excluded from the
    `broken` threshold's numerator entirely — their reason is `no_template`,
    a configuration gap rather than a redesign. So rung 2 returns `None`
    rather than an empty mapping, and a domain nobody has configured does not
    look like a domain that has been redesigned."""
    selector = SelectorStrategy("GBP")
    fields = await selector.extract(
        page("vantage-abrasives/product.html", "https://vantage-abrasives.test/catalog/x"),
        template=None,
    )
    assert fields is None, "no template must be distinguishable from nothing extracted"


async def test_a_hollow_jsonld_block_falls_through_instead_of_stopping_the_chain() -> None:
    """A real shape: an SEO plugin emits `schema.org/Product` with nothing in
    it. Rung 1 returning a mapping of empty values would stop the chain and
    leave the template unreachable on that page, so the chain checks
    `empty_extraction` rather than `is None`."""
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","name":""}'
        "</script></head><body>"
        '<main class="product"><h1 class="product__title">Real Title</h1>'
        '<div class="product__price">£9.99</div></main></body></html>'
    )
    hollow = FetchedPage(
        request_url="https://x.test/p",
        final_url="https://x.test/p",
        http_status=200,
        body=html,
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=10,
        fetch_path=FetchPath.STATIC,
    )

    result = await chain("GBP").extract(hollow, template=vantage_template())
    assert result.strategy is Strategy.SELECTOR
    assert result.fields["title"] == "Real Title"


async def test_a_fallback_selector_is_used_when_the_primary_resolves_nothing() -> None:
    """`FieldRule.fallback` existed with no test — mutation found it by
    deleting the branch and finding the suite green.

    It is the cheap half of surviving a partial redesign: a site that renames
    one class breaks one field, and a template carrying the old name as a
    fallback keeps extracting. Without a test, the first person to tidy that
    branch away would see nothing fail.
    """
    html = (
        '<main class="product"><h1 class="legacy__title">Renamed But Found</h1>'
        '<div class="product__price">£5.00</div>'
        '<div class="gallery"><img class="gallery__image" src="/a.jpg"/></div></main>'
    )
    moved = FetchedPage(
        request_url="https://x.test/p",
        final_url="https://x.test/p",
        http_status=200,
        body=html,
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=10,
        fetch_path=FetchPath.STATIC,
    )
    template = vantage_template()
    with_fallback = dict(template.extraction)
    with_fallback["title"] = FieldRule(
        selector=".product__title",
        fallback=".legacy__title",
        validation=(Rule(RuleName.NON_EMPTY),),
    )

    result = await chain("GBP").extract(moved, template=replace(template, extraction=with_fallback))

    assert result.fields["title"] == "Renamed But Found"
    assert result.strategy is Strategy.SELECTOR


def test_the_chain_cannot_reach_a_model_at_crawl_time() -> None:
    """ADR-0005: the LLM proposes rules during onboarding and never runs
    during a crawl. A chain that could reach rung 3 would be a defect
    however well it worked, so the composition is asserted."""
    names = [s.name for s in chain()._strategies]  # noqa: SLF001 - the composition is the subject
    assert names == [Strategy.STRUCTURED, Strategy.SELECTOR]
    assert Strategy.LLM not in names
