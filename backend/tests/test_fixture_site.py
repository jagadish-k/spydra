"""The fixture site is the thing every later test trusts (BUILD_PLAN 1.4).

So it gets its own tests. Not for the server's plumbing — for the properties
the extraction, politeness and redesign tests all *assume* about these files.
A fixture that quietly stops exercising its shape takes the test that depends
on it down with it, silently, and the test still passes.

The pairs are the point. Two of these files exist only in contrast with
another, and a single-file assertion cannot see that:

  - product-jsonld vs product-stripped — identical but for the JSON-LD block,
    so rung 1 must win on one and rung 2 on the other (spec 003 §1).
  - product-redesigned vs product-missing — both a 200 with nothing
    resolvable, and ADR-0030 separates them by prior observation, not by
    markup. A test that treats them the same has tested neither.
"""

import re
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fixtures.server import (
    DEFAULT_ROBOTS,
    OVERSIZED_MAX_MB,
    PAGES,
    ROBOTS,
    ROUTES,
    SLOW_IMAGE_DELAY_S,
    FixtureSite,
)

OLD_NORTHFIELD_SELECTORS = ("product__title", "product__price")


def _code(path: Path) -> str:
    """Markup with HTML comments stripped.

    Every assertion here runs on this rather than the raw file. The comments
    in these fixtures explain what they are *for*, which means they name the
    very selectors and reasons the assertions look for — a check over the raw
    text passes or fails on the documentation.
    """
    return re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)


@pytest.fixture(scope="module")
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


def test_every_route_serves_its_file(site: FixtureSite) -> None:
    for path in ROUTES:
        with urllib.request.urlopen(f"{site.base_url}{path}", timeout=5) as r:
            assert r.status == 200, path
            assert r.read(), f"{path} served an empty body"


def test_the_jsonld_twins_differ_only_by_the_jsonld_block() -> None:
    """Otherwise the chain-ordering test proves nothing.

    If the two pages differ in their markup as well, a rung-2 extraction on
    the stripped page might succeed or fail for reasons that have nothing to
    do with rung 1 having been skipped.
    """
    with_ld = _code(PAGES / "orbis-components/product-jsonld.html")
    without = _code(PAGES / "orbis-components/product-stripped.html")

    assert "application/ld+json" in with_ld
    assert "application/ld+json" not in without

    def strip_script(src: str) -> str:
        return re.sub(r'<script type="application/ld\+json">.*?</script>\s*', "", src, flags=re.S)

    assert strip_script(with_ld).split() == without.split(), (
        "the twins differ by more than the JSON-LD block, so a rung-ordering "
        "test against them would be measuring something else"
    )


def test_the_jsonld_fixture_is_a_real_schema_org_product() -> None:
    """Rung 1 uses extruct against schema.org/Product (spec 003 §1). A
    fixture with a typo'd @type exercises the fall-through, not the rung."""
    src = _code(PAGES / "orbis-components/product-jsonld.html")
    for required in ('"@type": "Product"', '"priceCurrency"', '"offers"', '"name"'):
        assert required in src, f"JSON-LD fixture is missing {required}"


def test_the_redesigned_page_resolves_none_of_the_old_selectors() -> None:
    """The redesign fixture's whole job: a 200, real product content, and a
    template that matches nothing (spec 003 §3). If an old class name
    survives, `empty_extraction` will not fire and the most valuable test in
    the suite silently stops testing."""
    code = _code(PAGES / "northfield/product-redesigned.html")
    present = [s for s in OLD_NORTHFIELD_SELECTORS if s in code]
    assert not present, f"the redesigned page still carries {present}"
    # ...and it must still be a product page, or it is a soft 404 instead.
    assert "Hex Head Set Screw" in code
    assert "£0.38" in code


def test_the_soft_404_has_no_product_and_still_returns_200(site: FixtureSite) -> None:
    """ADR-0030's reason for existing. The status is what makes it *soft*;
    serving 404 would make this fixture test nothing."""
    with urllib.request.urlopen(f"{site.base_url}/katalog/discontinued-item", timeout=5) as r:
        assert r.status == 200
        body = r.read().decode()

    code = re.sub(r"<!--.*?-->", "", body, flags=re.S).lower()
    assert "couldn't find that product" in code
    for product_ish in ("produkt__name", "produkt__preis", "£", "eur"):
        assert product_ish not in code, f"the soft 404 carries {product_ish!r}"


def test_the_rendered_page_is_empty_before_javascript_runs(site: FixtureSite) -> None:
    """Half of spec 012 §6's first criterion, and the half that is easy to
    lose: content present after render means nothing unless it is absent
    from the raw response."""
    with urllib.request.urlopen(
        f"{site.base_url}/katalog/stirnlochschluessel-30-80", timeout=5
    ) as r:
        raw = r.read().decode()

    assert "<script>" in raw, "the fixture is supposed to need JavaScript"
    markup = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    markup = re.sub(r"<!--.*?-->", "", markup, flags=re.S)
    assert "produkt__name" not in markup, (
        "the product is in the server HTML, so this fixture no longer "
        "distinguishes the static path from the rendered one"
    )


def test_crawl_delay_robots_is_a_floor_not_a_ceiling(site: FixtureSite) -> None:
    """Spec 002 §5. The fixture has to be a value that can only RAISE a
    configured delay, or the test built on it cannot tell the two apart."""
    req = urllib.request.Request(
        f"{site.base_url}/robots.txt", headers={"Host": "crawl-delay.test"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        assert "Crawl-delay: 10" in r.read().decode()


def test_robots_is_served_per_host(site: FixtureSite) -> None:
    """Politeness is per host (spec 002 §5), so one fixture host could not
    exercise Crawl-delay and disallow-all in the same run."""
    seen = {}
    for host in ("crawl-delay.test", "disallow-all.test", "anything-else.test"):
        req = urllib.request.Request(f"{site.base_url}/robots.txt", headers={"Host": host})
        with urllib.request.urlopen(req, timeout=5) as r:
            seen[host] = r.read().decode()

    assert "Crawl-delay" in seen["crawl-delay.test"]
    assert seen["disallow-all.test"].strip().endswith("Disallow: /")
    assert seen["anything-else.test"] == DEFAULT_ROBOTS.read_text()
    assert len(set(seen.values())) == 3, "two hosts answered with the same robots.txt"


def test_the_trap_is_genuinely_unbounded(site: FixtureSite) -> None:
    """BUILD_PLAN 2.5's caps must be the only thing that stops it. A trap
    that runs out of pages lets a missing cap pass."""
    path = "/trap/"
    for _ in range(12):
        with urllib.request.urlopen(f"{site.base_url}{path}", timeout=5) as r:
            body = r.read().decode()
        match = re.search(r'href="([^"]+)"', body)
        assert match, f"the trap stopped generating links at {path}"
        path = match.group(1)
    assert path.count("/") > 12


def test_nothing_in_the_fixtures_points_at_a_real_host() -> None:
    """AGENTS.md rule 2: these are written, not captured. An absolute URL to
    a real site is both a tell that someone pasted a page and a route by
    which a test could reach the network (rule 14)."""
    offenders = []
    for page in sorted(PAGES.rglob("*.html")):
        for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', _code(page)):
            if ".invalid" not in url and "example." not in url:
                offenders.append(f"{page.name}: {url}")
    assert not offenders, "absolute URLs to real hosts in fixtures:\n  " + "\n  ".join(offenders)


def test_every_robots_fixture_is_reachable_and_distinct() -> None:
    files = sorted(ROBOTS.glob("*.txt"))
    assert len(files) == 3, [f.name for f in files]
    assert len({f.read_text() for f in files}) == 3


# ---------------------------------------------------------------------------
# The generated shapes (BUILD_PLAN 1.5).
#
# Same reasoning as everything above: these exist so spec 012 §6 can be
# proven, and a generated response that quietly stops stalling, stops being
# oversized or stops raising a dialog takes its acceptance test down with it
# while the test still passes. The delay assertions are on OBSERVED elapsed
# time, never a patched clock.
# ---------------------------------------------------------------------------


def test_the_slow_route_actually_stalls_for_the_time_it_is_asked_for(site: FixtureSite) -> None:
    """It is what holds a render context open, so the context cap and the 503
    (spec 012 §2, §6) are observed rather than inferred. A route that
    returned instantly would make the fourth request succeed and the cap
    look broken."""
    start = time.monotonic()
    with urllib.request.urlopen(f"{site.base_url}/slow/700", timeout=10) as r:
        assert r.status == 200
        assert b"produkt__preis" in r.read()
    assert time.monotonic() - start >= 0.7


def test_the_slow_route_defaults_rather_than_erroring_on_a_bad_segment(
    site: FixtureSite,
) -> None:
    """A test writing these URLs by hand should get a slow page, not a stack
    trace that reads like a server fault."""
    start = time.monotonic()
    with urllib.request.urlopen(f"{site.base_url}/slow/not-a-number", timeout=10) as r:
        assert r.status == 200
    assert time.monotonic() - start >= 1.0


def test_the_slow_images_are_delayed_and_are_actually_images(site: FixtureSite) -> None:
    """The delay IS the mechanism behind "block_resources measurably reduces
    render time" (spec 012 §2, §6). Served instantly, a 24-image gallery
    renders at the same speed blocked or not, and that criterion becomes
    unfalsifiable."""
    start = time.monotonic()
    with urllib.request.urlopen(f"{site.base_url}/img/slow/01.png", timeout=10) as r:
        assert r.status == 200
        assert r.headers["content-type"] == "image/png"
        assert r.read().startswith(b"\x89PNG")
    assert time.monotonic() - start >= SLOW_IMAGE_DELAY_S


def test_the_image_heavy_page_references_the_delayed_images(site: FixtureSite) -> None:
    """A gallery pointing at instant images proves nothing, and the count has
    to be high enough that the delay shows through browser concurrency."""
    with urllib.request.urlopen(
        f"{site.base_url}/catalog/abrasives/discs/rfd-115-060/galerie", timeout=5
    ) as r:
        body = r.read().decode()
    assert body.count('src="/img/slow/') >= 12
    assert "produkt__preis" in body


def test_the_oversized_route_is_oversized_and_bounded(site: FixtureSite) -> None:
    """Spec 012 §3 caps the response at 10 MB and flags a truncation, so the
    fixture has to exceed it — and must not be a committed 20 MB blob, which
    the pre-commit hook refuses and no reviewer could read. The upper bound
    is here so a typo in a test cannot ask for 20 GB."""
    with urllib.request.urlopen(f"{site.base_url}/oversized/20", timeout=60) as r:
        assert r.status == 200
        assert len(r.read()) == 20 * 1024 * 1024

    with urllib.request.urlopen(f"{site.base_url}/oversized/9999", timeout=120) as r:
        assert len(r.read()) == OVERSIZED_MAX_MB * 1024 * 1024


def test_the_dialog_fixture_raises_its_dialogs_before_it_writes_the_product() -> None:
    """Spec 012 §6: "a page opening alert() does not hang the request". The
    ordering is the test's teeth — if the product were written first, a
    sidecar that hung on the dialog would still return the content and the
    criterion would pass against a broken guard."""
    code = _code(PAGES / "mertens/product-dialog.html")
    for dialog in ("alert(", "confirm(", "prompt("):
        assert dialog in code, f"the dialog fixture no longer opens {dialog}"
    assert code.index("alert(") < code.index("produkt__preis"), (
        "the product is written before the dialog, so this fixture would pass "
        "against a sidecar that hangs on alert()"
    )
