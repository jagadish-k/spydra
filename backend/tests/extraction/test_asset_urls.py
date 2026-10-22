"""`asset_urls` and the predicate it shares with the hash (BUILD_PLAN 1.12).

The point of this file is the **pairing**. `content_hash` excludes asset URLs
(spec 003 §4) and the enqueue picks them up (spec 008 §1), and if those two
ever disagree a URL falls between them — an image invisible to both change
detection and the asset pipeline. The last test here asserts the two halves
against each other rather than trusting that one import keeps them aligned.
"""

from decimal import Decimal

from spydra.domain.entities import ExtractedFields
from spydra.extraction.assets import asset_urls, is_asset_url
from spydra.extraction.hashing import normalise
from spydra.extraction.strategies.selector import SelectorStrategy
from tests.extraction.pages import page, vantage_template


async def test_the_fixture_gallery_is_enqueueable_in_page_order() -> None:
    """Through the real extraction, because the `absolute_url` transform is
    what makes these URLs absolute in the first place — a test with
    hand-written URLs would pass with that transform removed."""
    extracted = await SelectorStrategy().extract(
        page("vantage-abrasives/product.html", "https://vantage.test/catalog/rfd-115"),
        vantage_template(),
    )

    assert extracted is not None
    assert asset_urls(extracted) == (
        "https://vantage.test/img/rfd-115-060-a.jpg",
        "https://vantage.test/img/rfd-115-060-b.jpg",
    )


def test_order_is_kept_and_duplicates_lose_their_second_place() -> None:
    """`position` is the index (spec 001 §1), so a hero image listed twice
    keeps position 0 — and `UNIQUE (observation_id, source_url)` means the
    second copy has nowhere to go anyway."""
    fields: ExtractedFields = {
        "images": ["https://cdn.test/b.jpg", "https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]
    }

    assert asset_urls(fields) == ("https://cdn.test/b.jpg", "https://cdn.test/a.jpg")


def test_urls_are_found_wherever_the_extraction_put_them() -> None:
    """A `many` rule yields a sequence and a `pairs` transform yields a
    mapping, so both have to be walked — a top-level-only scan would miss a
    datasheet image inside a spec table."""
    fields: ExtractedFields = {
        "title": "Resin Fibre Disc",
        "images": ["https://cdn.test/a.jpg"],
        "specs": {"Diagram": "https://cdn.test/diagram.png", "Grit": "P60"},
    }

    assert asset_urls(fields) == ("https://cdn.test/a.jpg", "https://cdn.test/diagram.png")


def test_a_relative_path_is_not_an_asset_url() -> None:
    """The `absolute_url` transform makes asset URLs absolute (spec 003 §2).
    A bare path in a field that skipped it is as likely to be a product code,
    and guessing puts junk in `asset_queue` AND drops a real field out of the
    hash — the same mistake twice, in opposite directions."""
    assert not is_asset_url("/img/a.jpg")
    assert asset_urls({"sku": "/VA-RFD-115-060"}) == ()


def test_the_scheme_is_matched_whatever_its_case() -> None:
    """A page that shouts its scheme is a page whose images would otherwise
    be hashed — and then a re-upload reports that page, and only that page,
    as changed."""
    assert is_asset_url("HTTPS://CDN.test/A.jpg")
    assert asset_urls({"images": ["HTTP://cdn.test/a.jpg"]}) == ("HTTP://cdn.test/a.jpg",)


def test_text_and_numbers_are_not_urls() -> None:
    assert not is_asset_url("Resin Fibre Disc")
    assert not is_asset_url(Decimal("14.75"))
    assert not is_asset_url(None)
    assert asset_urls({"title": "Resin Fibre Disc", "price": Decimal("14.75")}) == ()


def test_everything_enqueued_is_excluded_from_the_hash_and_the_reverse() -> None:
    """The one that matters.

    Two definitions of "asset URL" would let a value fall between the hash's
    exclusion and the enqueue's pickup. This asserts the invariant directly:
    nothing `asset_urls` returns survives into the normalised form, and
    nothing that survives is an asset URL. It fails if either side grows its
    own copy of the predicate — which is how it would actually happen.
    """
    # Deliberately varied: two schemes, four hosts, upper case, a port, and
    # a URL nested in a mapping. A copy of the predicate narrowed to any one
    # of those shapes — `startswith("https://cdn.")` is the realistic
    # mistake — keeps the others in the hash while the enqueue takes them,
    # and the assertions below catch exactly that.
    fields: ExtractedFields = {
        "title": "Resin Fibre Disc",
        "images": ["https://cdn.test/a.jpg", "http://img.other.test/b.jpg"],
        "datasheet": "HTTPS://Files.Vantage.test:8443/sheet.pdf",
        "sku": "VA-RFD-115-060",
        "specs": {"Diagram": "http://d.example.test/d.png", "Grit": "P60"},
    }

    enqueued = set(asset_urls(fields))
    hashed = normalise(fields)

    assert len(enqueued) == 4, "the fixture has to carry every shape or this proves nothing"
    assert not any(is_asset_url(value) for value in _leaves(hashed))
    assert not (enqueued & set(_leaves(hashed)))
    # And the non-asset fields are still there, so the exclusion is not just
    # "the hash is empty".
    assert hashed["title"] == "Resin Fibre Disc"
    assert hashed["sku"] == "VA-RFD-115-060"


def _leaves(value: object) -> list[object]:
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return [value]
