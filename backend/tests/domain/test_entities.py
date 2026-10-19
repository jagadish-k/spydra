"""The entities (spec 001 §3)."""

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from spydra.domain import (
    DiscoveryRules,
    FetchedPage,
    FetchPath,
    FetchRequest,
    FieldRule,
    Observation,
    PageKind,
    ProposedBy,
    Rule,
    RuleName,
    Strategy,
    Template,
    Transform,
    TransformName,
    ValidationResult,
)
from spydra.domain.ids import DomainId, PageId, RunId, TemplateId

NOW = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)


def a_template(**extraction: FieldRule) -> Template:
    return Template(
        id=TemplateId(1),
        domain_id=DomainId(1),
        name="product",
        url_pattern=r"^/products/",
        page_kind=PageKind.PRODUCT,
        version=1,
        is_active=True,
        discovery=DiscoveryRules(),
        extraction=extraction,
        proposed_by=ProposedBy.HUMAN,
    )


def an_observation(**validation: ValidationResult) -> Observation:
    return Observation(
        page_id=PageId(1),
        run_id=RunId(1),
        template_id=TemplateId(1),
        observed_at=NOW,
        http_status=200,
        strategy=Strategy.SELECTOR,
        content_hash=b"\x01\x02",
        fields={"price": Decimal("12.3400"), "title": "A thing"},
        validation=validation,
    )


@pytest.mark.parametrize(
    "entity",
    [
        a_template(title=FieldRule(selector="h1")),
        an_observation(),
        FetchRequest(url="https://example.test/robots.txt", user_agent="UA/1.0"),
        DiscoveryRules(),
        Transform(TransformName.TRIM),
        Rule(RuleName.NON_EMPTY),
    ],
)
def test_entities_are_frozen(entity: object) -> None:
    """Observations are append-only (ADR-0007, AGENTS.md rule 13).

    A mutable entity would make that a convention rather than a type, and the
    rule it protects — never UPDATE a page_observations row — is the one that
    makes price history possible at all.
    """
    assert dataclasses.is_dataclass(entity)
    field = next(iter(dataclasses.fields(entity))).name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(entity, field, "mutated")


def test_a_failing_field_is_recorded_and_routes_nothing() -> None:
    """ADR-0027: validation is evidence, never control flow.

    This replaces three tests that asserted the opposite — one of them named
    `test_routing_is_the_intersection_with_the_templates_required_fields`.
    They were written against the implementation rather than the spec, and
    TESTING.md §2 now says what this says.
    """
    o = an_observation(
        price=ValidationResult(RuleName.CURRENCY, ok=False, saw="POA"),
        title=ValidationResult(RuleName.NON_EMPTY, ok=True),
    )

    # Recorded, per field, with what it saw — that is the whole contract.
    assert o.failed_validation == frozenset({"price"})
    assert o.validation["price"].saw == "POA"

    # And the observation is still written with whatever resolved: spec 003
    # §3 says partial data is never discarded.
    assert o.fields["price"] == Decimal("12.3400")


def test_nothing_in_the_entities_computes_a_required_field_set() -> None:
    """The reader ADR-0027 deleted must not come back.

    `Template.required_fields` existed and was the only consumer of the flag.
    ADR-0027 says `required` "becomes inert ... nothing reads it", and the
    threshold it fed is now the `empty_extraction` rate. A re-added property
    would pre-wire exactly the re-attachment the ADR warns against.
    """
    assert not hasattr(a_template(title=FieldRule(selector="h1")), "required_fields")


def test_a_transform_can_carry_arguments() -> None:
    """`pairs(th, td)` is the reason Transform is a dataclass and not a bare
    enum member (spec 003 §2)."""
    assert Transform(TransformName.PAIRS, ("th", "td")).args == ("th", "td")
    assert Transform(TransformName.TRIM).args == ()


def test_a_rule_can_carry_an_argument() -> None:
    assert Rule(RuleName.MIN_COUNT, 3).arg == 3
    assert Rule(RuleName.MATCHES, r"^\d+$").arg == r"^\d+$"
    assert Rule(RuleName.NON_EMPTY).arg is None


def test_fetch_request_will_not_default_its_user_agent() -> None:
    """ADR-0004 makes honest identification a property of every request.

    A default here would let a code path exist that sends httpx's user-agent
    to a real supplier, and that path would be found by the supplier.
    """
    with pytest.raises(TypeError):
        FetchRequest(url="https://example.test/")  # type: ignore[call-arg]


def a_page(final_url: str) -> FetchedPage:
    return FetchedPage(
        request_url="https://example.test/products/1",
        final_url=final_url,
        http_status=200,
        body="<html></html>",
        headers={"content-type": "text/html"},
        fetched_at=NOW,
        elapsed_ms=412,
        fetch_path=FetchPath.STATIC,
    )


def test_redirect_is_detected_from_the_final_url() -> None:
    assert not a_page("https://example.test/products/1").redirected
    assert a_page("https://example.test/products/1-slug").redirected


def test_fetch_path_records_which_adapter_served_the_page() -> None:
    """So an `auto` domain falling back to static is visible in the data
    rather than inferred from a log (spec 001 §3, ADR-0016)."""
    assert a_page("https://example.test/products/1").fetch_path is FetchPath.STATIC
    assert set(FetchPath) == {FetchPath.STATIC, FetchPath.RENDERED}
