"""The `templates.extraction` JSONB codec (BUILD_PLAN 1.13).

No database: these are the two pure functions every template row passes
through on its way into a crawl. The approved template is `1.10`'s
`vantage_template`, the one the chain tests prove against the fixture, so a
codec that loses a transform argument or a validation rule shows up as a
template that no longer means what the operator approved.
"""

from spydra.adapters.postgres.templates import extraction_from_json, extraction_to_json
from spydra.domain.entities import FieldRule, Rule, Transform
from spydra.domain.enums import RuleName, TransformName
from tests.extraction.pages import vantage_template


def test_an_approved_template_survives_a_round_trip_through_jsonb_unchanged() -> None:
    rules = vantage_template().extraction

    assert extraction_from_json(extraction_to_json(rules)) == rules


def test_steps_with_arguments_and_a_fallback_survive_a_round_trip() -> None:
    """The vantage template has no transform that takes arguments, so this is
    the case it cannot cover: `pairs` with its two selectors, a rule with an
    argument, and a fallback selector."""
    rules = {
        "specs": FieldRule(
            selector=".product__specs tr",
            many=True,
            transform=(Transform(TransformName.PAIRS, ("th", "td")),),
            validation=(Rule(RuleName.MIN_COUNT, 3),),
        ),
        "price": FieldRule(
            selector=".product__price",
            transform=(
                Transform(TransformName.STRIP_CURRENCY),
                Transform(TransformName.PARSE_DECIMAL),
            ),
            validation=(Rule(RuleName.CURRENCY),),
            fallback="[itemprop=price]",
        ),
    }

    assert extraction_from_json(extraction_to_json(rules)) == rules


def test_a_stored_required_true_is_not_decoded_into_the_rule() -> None:
    """ADR-0027: `required` is inert. A prior template version may still
    carry the key (spec 001 §3), and reading it back must not resurrect it."""
    decoded = extraction_from_json({"title": {"selector": ".product__title", "required": True}})

    assert decoded["title"].required is FieldRule(selector=".x").required
    assert decoded["title"] == FieldRule(selector=".product__title")


def test_the_encoded_form_never_carries_required() -> None:
    encoded = extraction_to_json(vantage_template().extraction)

    assert all("required" not in field for field in encoded.values())
