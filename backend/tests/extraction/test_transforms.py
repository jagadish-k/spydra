"""The transform table, against a table of fixtures (spec 003 §5).

Spec 003 §5's last line asks for exactly this: "Transform chains are
unit-tested against a table of fixtures, **including European decimal commas
and multi-currency pages**."

The two transforms worth the most attention are the two that can invent data:
`parse_decimal`, where a guess turns €1,234 into €1.234, and `detect_currency`,
where a guess puts a plausible number under the wrong symbol. Both return
`None` instead.
"""

from decimal import Decimal

import pytest

from spydra.extraction.transforms import (
    absolute_url,
    detect_currency,
    pairs,
    parse_decimal,
    strip_currency,
    trim,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Resin   Fibre\n Disc ", "Resin Fibre Disc"),
        ("\t\nIn stock\t", "In stock"),
        ("", ""),
    ],
)
def test_trim_collapses_whitespace(raw: str, expected: str) -> None:
    assert trim(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected", "why"),
    [
        ("£14.75", Decimal("14.75"), "sterling"),
        ("$1,234.50", Decimal("1234.50"), "thousands separator with an explicit decimal"),
        ("24,90 EUR", Decimal("24.90"), "European decimal comma — spec 003 §5 names this"),
        ("€1.234,56", Decimal("1234.56"), "German: dot thousands, comma decimal"),
        ("-1.50", Decimal("-1.50"), "the sign survives"),
        ("3.40", Decimal("3.40"), "bare number"),
    ],
)
def test_parse_decimal_handles_the_shapes_a_catalogue_actually_uses(
    raw: str, expected: Decimal, why: str
) -> None:
    assert parse_decimal(raw) == expected, why


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("POA", "spec 003 §5 names this: a validation failure, never 0.00"),
        ("Call for price", "prose is not a price"),
        ("", "an empty selector result is not zero"),
        ("1,234", "AMBIGUOUS: 1234 in English, 1.234 in German — spec 003 §2 fails loudly"),
        ("1.234", "the same ambiguity with the separators swapped"),
        ("—", "a dash is a placeholder, not a number"),
    ],
)
def test_parse_decimal_returns_none_rather_than_guessing(raw: str, why: str) -> None:
    """The most important test in this file.

    Every one of these becoming `0.00` would be a price the operator can
    neither see nor explain — a catalogue of zeros looks like data, which is
    spec 003 §3's "produces no error and no crash, just wrong data". And the
    two ambiguous ones are worse: `1,234` silently read as `1.234` is a
    thousandfold error on a real number.
    """
    assert parse_decimal(raw) is None, why


@pytest.mark.parametrize(
    ("raw", "expected", "why"),
    [
        ("£14.75", "14.75", "the symbol goes"),
        ("$1,234.50", "1234.50", "two separators: the comma is thousands"),
        ("€1.234,56", "1234,56", "the same, with the roles swapped"),
        ("-1.50", "-1.50", "the sign survives"),
        ("1 234,00 SEK", "1234,00", "the code goes too, and the decimal comma stays"),
        ("24,90", "24,90", "ONE separator is left alone — it is a decimal comma"),
        ("1,234", "1,234", "and the ambiguous case travels on to be refused, not guessed"),
    ],
)
def test_strip_currency_keeps_the_sign_and_the_decimal(raw: str, expected: str, why: str) -> None:
    """A regex that stripped everything non-numeric would turn `-1.50` into
    `150` — a sign error of a factor of a hundred, which is why the sign and
    the decimal separator are explicitly preserved."""
    assert strip_currency(raw) == expected, why


@pytest.mark.parametrize(
    ("raw", "page", "domain", "expected", "why"),
    [
        ("£14.75", None, None, "GBP", "the symbol is the first source of truth"),
        ("24,90 €", None, "GBP", "EUR", "the symbol beats the domain default"),
        ("14.75", "USD", "GBP", "USD", "the page's declaration beats the domain default"),
        ("14.75", None, "GBP", "GBP", "the domain default is last"),
        ("14.75", None, None, None, "no source at all is a FAILURE, not a guess"),
    ],
)
def test_currency_detection_follows_the_spec_order_and_never_guesses(
    raw: str, page: str | None, domain: str | None, expected: str | None, why: str
) -> None:
    """Spec 003 §2: "symbol first, then the page's declared currency, then
    the domain default. A price without a determinable currency is a
    **validation failure**, not a guess."

    The last row is the one that matters. A wrong currency is worse than a
    missing one, because a missing one is visible in the validation record
    and a wrong one looks exactly like data.
    """
    assert detect_currency(raw, page, domain) == expected, why


def test_absolute_url_resolves_against_the_page() -> None:
    page = "https://vantage-abrasives.test/catalog/abrasives/discs/rfd-115-060"
    assert absolute_url("/img/a.jpg", page) == "https://vantage-abrasives.test/img/a.jpg"
    assert absolute_url("b.jpg", page) == (
        "https://vantage-abrasives.test/catalog/abrasives/discs/b.jpg"
    )
    assert absolute_url("https://cdn.test/c.jpg", page) == "https://cdn.test/c.jpg"


def test_pairs_builds_a_spec_table_and_drops_an_unpaired_cell() -> None:
    """A spec table with a stray `th` is a real shape — a row that is a
    heading. Pairing it with nothing would put `{"Notes": None}` into JSONB."""
    assert pairs(["Diameter", "115 mm", "Grit", "P60"]) == {"Diameter": "115 mm", "Grit": "P60"}
    assert pairs([" Diameter ", "  115  mm "]) == {"Diameter": "115 mm"}
    assert pairs(["Odd"]) == {}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("CA$12.50", "CAD"),
        ("A$12.50", "AUD"),
        ("NZ$12.50", "NZD"),
        ("HK$12.50", "HKD"),
        ("US$12.50", "USD"),
        ("$12.50", "USD"),
    ],
)
def test_a_dollar_prefixed_symbol_names_its_own_currency(raw: str, code: str) -> None:
    """Multi-currency pages (spec 003 §5) are where the dollars collide: `$`
    is a substring of `CA$`, `A$`, `NZ$`, `HK$` and `US$`. Matched short
    symbol first, a Canadian price is recorded as US dollars — a plausible
    number under the wrong currency, which spec 003 §2 ranks below a missing
    one. The amount has to survive the prefix too: a stripped `CA` left on
    the number is not a decimal."""
    assert detect_currency(raw, None, None) == code
    assert strip_currency(raw) == "12.50"
    assert parse_decimal(raw) == Decimal("12.50")
