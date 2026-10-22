"""`content_hash` against spec 003 §4 and §5 (BUILD_PLAN 1.11).

Spec 003 §5's criterion is one line — "re-extracting an unchanged page
produces an identical `content_hash`" — and it is the easiest criterion in
the project to pass vacuously: a hash of a constant passes it, and so does a
hash that ignores its input. So every test here is paired. Each thing that
must NOT change the hash is asserted beside something that MUST, and the
pair is what has content.
"""

from decimal import Decimal

import pytest

from spydra.domain.entities import ExtractedFields
from spydra.extraction.hashing import content_hash, is_substantive, normalise
from spydra.extraction.strategies.selector import SelectorStrategy
from tests.extraction.pages import page, vantage_template


async def test_re_extracting_an_unchanged_page_yields_an_identical_hash() -> None:
    """Spec 003 §5, through the real chain rather than through a literal.

    The fields come from extracting `1.4`'s fixture twice. A test that hashed
    a hand-written dict twice would pass against an extraction that was
    non-deterministic, which is the only way this criterion can actually
    fail.
    """
    fixture = page("vantage-abrasives/product.html", "https://vantage.test/catalog/rfd-115")
    strategy = SelectorStrategy()

    first = await strategy.extract(fixture, vantage_template())
    second = await strategy.extract(fixture, vantage_template())

    assert first is not None and second is not None
    assert content_hash(first) == content_hash(second)
    # Not vacuous: the extraction actually produced something.
    assert first["title"] == "Resin Fibre Disc 115mm P60"


async def test_the_hash_is_32_bytes_of_binary() -> None:
    """`page_observations.content_hash` is BYTEA. A hex string there is a
    64-byte value that compares equal to nothing anyone expects."""
    digest = content_hash({"title": "x"})

    assert isinstance(digest, bytes)
    assert len(digest) == 32


# ---------------------------------------------------------------------------
# Normalisation: spec 003 §4's four rules, each as a pair
# ---------------------------------------------------------------------------


def test_key_order_does_not_change_the_hash_but_a_value_does() -> None:
    assert content_hash({"a": "1", "b": "2"}) == content_hash({"b": "2", "a": "1"})
    assert content_hash({"a": "1", "b": "2"}) != content_hash({"a": "1", "b": "3"})


def test_collapsed_whitespace_is_not_a_change_but_lost_words_are() -> None:
    """A reflowed template is not news; a deleted word is."""
    assert content_hash({"d": "Zirconia  resin\n  fibre"}) == content_hash(
        {"d": "Zirconia resin fibre"}
    )
    assert content_hash({"d": "Zirconia resin fibre"}) != content_hash({"d": "Zirconiaresinfibre"})


def test_one_decimal_value_has_one_hash_however_it_is_spelled() -> None:
    """`10.50`, `10.5`, `1.05E+1` and the int-vs-Decimal difference between
    the two extraction rungs are all one value."""
    assert content_hash({"p": Decimal("10.50")}) == content_hash({"p": Decimal("10.5")})
    assert content_hash({"p": Decimal("10.50")}) == content_hash({"p": Decimal("1.05E+1")})
    assert content_hash({"n": 5}) == content_hash({"n": Decimal("5")})
    assert content_hash({"p": Decimal("10.50")}) != content_hash({"p": Decimal("10.55")})


def test_a_whole_number_does_not_become_an_exponent() -> None:
    """`Decimal("100").normalize()` is `Decimal("1E+2")`.

    Hashed through `str()` that is a different string from `100`, so the
    guard is the `f` presentation type. Without it, a price of 100 and a
    price of 100 hash differently depending on which rung produced them —
    a price that did not move, reported as a change.
    """
    assert "E" not in str(normalise({"p": Decimal("100")})["p"])
    assert content_hash({"p": Decimal("100")}) == content_hash({"p": 100})
    assert content_hash({"p": Decimal("100")}) != content_hash({"p": Decimal("1000")})


def test_asset_urls_are_excluded_and_the_rest_of_the_page_is_not() -> None:
    """Spec 003 §4: "asset URLs excluded (they are hashed separately by
    content)".

    The pair is the point. A re-uploaded image must not mark the page
    changed; a changed title must.
    """
    with_images = {
        "title": "Resin Fibre Disc",
        "images": ["https://cdn.vantage.test/a.jpg?v=1"],
    }
    rehosted = {
        "title": "Resin Fibre Disc",
        "images": ["https://cdn.vantage.test/a.jpg?v=99", "https://cdn.vantage.test/b.jpg"],
    }
    retitled = {"title": "Resin Fibre Disc 115mm", "images": with_images["images"]}

    assert content_hash(with_images) == content_hash(rehosted)
    assert content_hash(with_images) != content_hash(retitled)
    assert "images" not in normalise(with_images)


def test_a_relative_path_is_not_treated_as_an_asset_url() -> None:
    """`absolute_url` makes asset URLs absolute (spec 003 §2), so a bare
    path in a field that skipped it is as likely to be a product code."""
    assert "sku" in normalise({"sku": "/VA-RFD-115-060"})


def test_the_prices_raw_text_is_evidence_and_not_hashed() -> None:
    """`raw` exists for spec 003 §3's `{"rule": "currency", "saw": "POA"}`.

    A markup change from `£10.50` to `GBP 10.50` leaves the price identical,
    and hashing the raw text would report it as a change on every page of the
    catalogue at once — the churn §4 rejects raw HTML for, arriving through
    the back door.
    """
    symbol: ExtractedFields = {
        "price": {"amount": Decimal("10.50"), "currency": "GBP", "raw": "£10.50"}
    }
    code: ExtractedFields = {
        "price": {"amount": Decimal("10.50"), "currency": "GBP", "raw": "GBP 10.50"}
    }
    dearer: ExtractedFields = {
        "price": {"amount": Decimal("11.50"), "currency": "GBP", "raw": "£11.50"}
    }

    assert content_hash(symbol) == content_hash(code)
    assert content_hash(symbol) != content_hash(dearer)


def test_a_spec_table_that_happens_to_have_a_raw_row_keeps_it() -> None:
    """The `raw` drop is scoped to the price composite — a mapping carrying
    `amount` or `currency`. A `pairs` transform over a spec table whose
    heading is "Raw" is data, and dropping it would lose a real change."""
    one = {"specs": {"raw": "Zirconia"}}
    other = {"specs": {"raw": "Aluminium oxide"}}

    assert content_hash(one) != content_hash(other)


def test_empty_fields_are_dropped_but_a_genuine_zero_is_not() -> None:
    """Dropped through `is_empty`, the same function `empty_extraction` is
    built on (ADR-0027) — not a second notion of empty.

    The reason it matters: adding a field to a template that matches on no
    page would otherwise change the hash of every page in the domain and
    report the whole catalogue as redesigned. The second assertion is the
    line that keeps `0` out of that: a price of zero is data.
    """
    assert content_hash({"title": "x"}) == content_hash({"title": "x", "price": None})
    assert content_hash({"title": "x"}) == content_hash({"title": "x", "price": "  "})
    assert content_hash({"title": "x"}) == content_hash({"title": "x", "specs": {}})
    assert content_hash({"title": "x"}) == content_hash({"title": "x", "images": []})

    assert content_hash({"title": "x"}) != content_hash({"title": "x", "stock": Decimal("0")})
    assert content_hash({"title": "x"}) != content_hash({"title": "x", "stock": 0})


def test_a_flag_is_not_a_number() -> None:
    """`isinstance(True, int)` is `True` and `Decimal(True)` is `1`, so
    without the bool branch a flag and a quantity of one hash the same."""
    assert content_hash({"f": True}) != content_hash({"f": Decimal("1")})
    assert content_hash({"f": True}) != content_hash({"f": False})


def test_sequence_order_is_part_of_the_content() -> None:
    """A re-ordered breadcrumb is a real site change; sorting the list here
    would hide it."""
    assert content_hash({"category_path": ["Abrasives", "Discs"]}) != content_hash(
        {"category_path": ["Discs", "Abrasives"]}
    )


def test_nested_values_are_normalised_all_the_way_down() -> None:
    """The recursion earns itself: a `pairs` transform produces a mapping,
    and a spec sheet reflowed inside its table is not a change either."""
    reflowed = {"specs": {"Max  RPM": "13300", "Grit": " P60 "}}
    tidy = {"specs": {"Max RPM": "13300", "Grit": "P60"}}

    assert content_hash(reflowed) == content_hash(tidy)
    assert content_hash(tidy) != content_hash({"specs": {"Max RPM": "13300", "Grit": "P80"}})


# ---------------------------------------------------------------------------
# Nothing to compare is not "the same" (spec 003 §4, review finding B3)
# ---------------------------------------------------------------------------

IMAGE_ONLY: ExtractedFields = {"images": ["https://cdn.vantage-abrasives.test/a.jpg"]}


def test_an_extraction_with_nothing_comparable_has_no_hash() -> None:
    """Spec 003 §4: "When nothing survives normalisation ... there is **no
    hash**".

    A digest of `{}` would be one value shared by every empty page and every
    image-only page in the database, and equal digests are what `unchanged`
    is decided on — so each of those pages would read as "same as last time"
    from its second crawl onward. The third assertion is the pair: one real
    field and there is a hash again.
    """
    assert content_hash({}) is None
    assert content_hash(IMAGE_ONLY) is None
    assert content_hash({**IMAGE_ONLY, "title": "Resin Fibre Disc"}) is not None


@pytest.mark.parametrize(
    ("fields", "expected", "why"),
    [
        ({}, False, "nothing extracted"),
        (IMAGE_ONLY, False, "asset URLs are excluded from the comparison"),
        ({"title": "  ", "images": []}, False, "values that are empty after trim"),
        ({"title": "Resin Fibre Disc"}, True, "one real field"),
        ({**IMAGE_ONLY, "title": "Resin Fibre Disc"}, True, "content beside the images"),
        ({"stock": 0}, True, "a genuine zero is content"),
    ],
    ids=["nothing", "image-only", "blank", "title", "title-and-images", "zero"],
)
def test_substantive_means_something_survives_normalisation(
    fields: ExtractedFields, expected: bool, why: str
) -> None:
    """`is_substantive` and `content_hash` answer one question from two
    sides — "is there anything to compare?" — so they are asserted together.
    If they drifted, the chain could stop on a rung whose result the writer
    then refuses to hash, or keep looking past one it would have hashed."""
    assert is_substantive(fields) is expected, why
    assert (content_hash(fields) is not None) is expected, why
