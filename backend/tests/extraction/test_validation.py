"""The validation rules themselves (spec 003 §3, BUILD_PLAN 1.10).

The chain tests exercise validation through a real page; these exercise the
rules directly, because three of them had no coverage at all and the gaps
were only visible by mutation:

- the **currency** rule's non-composite branch returned `True` for anything;
- the composite branch ignored a **missing currency code** entirely;
- every rule other than `non_empty` and `currency` was untested.

A validation rule that always passes is worse than no rule: spec 003 §3
calls silent extraction failure "the system's most important failure mode —
it produces no error and no crash, just wrong data", and these records are
the only place that failure becomes visible.
"""

from decimal import Decimal

import pytest

from spydra.domain.entities import FieldRule, FieldValue, Rule
from spydra.domain.enums import RuleName
from spydra.extraction.validation import validate, validate_field


def rule(name: RuleName, arg: str | int | None = None) -> tuple[Rule, ...]:
    return (Rule(name, arg),)


# ---------------------------------------------------------------------------
# currency — both halves, and both branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ({"amount": Decimal("3.40"), "currency": "GBP", "raw": "£3.40"}, "a real price"),
        (Decimal("3.40"), "a bare decimal, for a rung that emits one"),
        (3, "an integer amount is still an amount"),
    ],
)
def test_the_currency_rule_passes_a_determinable_price(value: FieldValue, why: str) -> None:
    assert validate_field(value, rule(RuleName.CURRENCY)) is None, why


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ({"amount": None, "currency": "GBP", "raw": "POA"}, "POA — spec 003 §5 names it"),
        (
            {"amount": Decimal("3.40"), "currency": None, "raw": "3.40"},
            "a NUMBER WITH NO CURRENCY: spec 003 §2 makes this a failure, not a guess",
        ),
        (
            {"amount": Decimal("3.40"), "currency": "POUNDS", "raw": "3.40"},
            "not a 3-letter ISO-4217 code — spec 003 §3 says three letters",
        ),
        ({"amount": Decimal("3.40"), "currency": "", "raw": "3.40"}, "an empty code is no code"),
        ("POA", "a bare string is not a price"),
        (None, "nothing resolved"),
        ("", "an empty selector result"),
        ([Decimal("3.40")], "a list is not a price"),
    ],
)
def test_the_currency_rule_fails_anything_it_cannot_determine(value: FieldValue, why: str) -> None:
    """The second row is the one mutation found missing.

    A price whose amount parses but whose currency could not be determined
    was passing validation — so a catalogue could fill with plausible numbers
    carrying no currency at all, and nothing would say so. Spec 003 §2 is
    explicit: "A price without a determinable currency is a **validation
    failure**, not a guess."
    """
    failure = validate_field(value, rule(RuleName.CURRENCY))
    assert failure is not None, why
    assert failure.ok is False
    assert failure.rule is RuleName.CURRENCY


# ---------------------------------------------------------------------------
# the rest of spec 003 §3's table, which had no tests at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "arg", "passes", "fails"),
    [
        (RuleName.NON_EMPTY, None, ["x", ["a"], {"k": "v"}, 0], [None, "", "   ", [], {}]),
        (
            RuleName.URL,
            None,
            ["https://a.test/x", "http://a.test"],
            ["/relative", "ftp://a.test", "a.test", None, ""],
        ),
        (RuleName.INTEGER, None, [7, "7", "-7"], ["7.5", "seven", None, "", True]),
        (
            RuleName.DATE,
            None,
            ["2026-10-21", "2026-10-21T14:00:00+00:00"],
            # 7 and None are not dates; a `datetime` OBJECT is not tested
            # because `FieldValue` cannot hold one and no transform produces
            # one — the branch that accepted it was dead and is gone.
            ["21/10/2026", "not a date", None, 7],
        ),
        (RuleName.MIN_COUNT, 2, [["a", "b"], ["a", "b", "c"]], [["a"], [], None, "ab"]),
        (RuleName.MATCHES, r"^VA-", ["VA-RFD-115"], ["RFD-115", None, 7]),
    ],
)
def test_every_rule_passes_what_it_should_and_fails_what_it_should(
    name: RuleName,
    arg: str | int | None,
    passes: list[FieldValue],
    fails: list[FieldValue],
) -> None:
    """One table, both directions. A rule tested only on values it accepts is
    indistinguishable from a rule that accepts everything — which is exactly
    what mutation found for `currency`.

    Two rows carry a deliberate trap. `non_empty` must pass `0`, because a
    genuine zero is data; and `integer` must **fail** `True`, because
    `isinstance(True, int)` is true in Python and a boolean reaching an
    integer field means something upstream went wrong.
    """
    for value in passes:
        assert validate_field(value, rule(name, arg)) is None, f"{name} should pass {value!r}"
    for value in fails:
        assert validate_field(value, rule(name, arg)) is not None, f"{name} should fail {value!r}"


def test_the_first_failing_rule_is_the_one_reported() -> None:
    """`page_observations.validation` stores one result per field (spec 003
    §3's `{field: {rule, ok, saw}}`), and the first failing rule is the one
    that explains the field. Reporting the last would blame `matches` for a
    field that was empty."""
    failure = validate_field("", (Rule(RuleName.NON_EMPTY), Rule(RuleName.MATCHES, "^x")))
    assert failure is not None
    assert failure.rule is RuleName.NON_EMPTY


def test_a_field_with_no_rules_cannot_fail() -> None:
    """Most fields carry no validation, and an empty rule tuple must not be
    read as "nothing passed"."""
    assert validate_field(None, ()) is None
    assert validate({"title": None}, {"title": FieldRule(selector=".t")}) == {}


def test_validate_reports_the_field_name_against_its_failure() -> None:
    """The operator reads this map to find which selector broke, so the key
    has to be the field."""
    rules = {
        "title": FieldRule(selector=".t", validation=(Rule(RuleName.NON_EMPTY),)),
        "sku": FieldRule(selector=".s", validation=(Rule(RuleName.MATCHES, "^VA-"),)),
    }
    results = validate({"title": "Fine", "sku": "XX-1"}, rules)

    assert set(results) == {"sku"}
    assert results["sku"].rule is RuleName.MATCHES
    assert results["sku"].saw == "XX-1"


def test_a_long_value_is_truncated_in_the_record() -> None:
    """A whole product description in a validation record is noise, and these
    records go into JSONB on every observation."""
    failure = validate_field("x" * 500, rule(RuleName.MATCHES, "^nope"))
    assert failure is not None
    assert failure.saw is not None
    assert len(failure.saw) <= 120
    assert failure.saw.endswith("...")
