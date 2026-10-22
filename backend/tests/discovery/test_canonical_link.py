"""Spec 004 §2 step 7, and steps 1–6 over Halden's served HTML (BUILD_PLAN 2.2).

`canonical_link(html, page_url)` is the page's own answer to "what is my
URL", honoured only on the page's own scheme and host. The unit cases are
inline markup because each one is a single `<link>` and the attribute *is*
the case. The Halden cases are read from what `FixtureSite` actually serves,
so a fixture that stops carrying a spelling fails here, not in a later test
that quietly passes for the wrong reason.
"""

import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from urllib.parse import parse_qsl, urljoin, urlsplit

import pytest
from selectolax.lexbor import LexborHTMLParser

from spydra.discovery.canonical import canonical_link
from spydra.domain.urls import canonical_url
from tests.fixtures.server import FixtureSite

HOST = "halden.test"
H = f"http://{HOST}"
PAGE = f"{H}/shop/cutting/blades/p/HT-SB-001"


def head(*links: str) -> str:
    return f"<html><head>{''.join(links)}</head><body><h1>x</h1></body></html>"


# ---------------------------------------------------------------------------
# canonical_link: what it honours
# ---------------------------------------------------------------------------


def test_a_same_host_absolute_canonical_is_returned() -> None:
    html = head(f'<link rel="canonical" href="{H}/shop/p/HT-SB-001">')
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001"


def test_a_root_relative_canonical_is_resolved_against_the_page() -> None:
    html = head('<link rel="canonical" href="/shop/p/HT-SB-001">')
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001"


def test_a_path_relative_canonical_is_resolved_against_the_page() -> None:
    html = head('<link rel="canonical" href="../../../p/HT-SB-001">')
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001"


def test_the_canonical_is_itself_canonicalised() -> None:
    """Step 7 names a URL; steps 1–6 still decide its spelling, or the same
    page filed under its own canonical twice would be two rows."""
    html = head(
        '<link rel="canonical" '
        'href="HTTP://HALDEN.TEST:80/shop//p/./HT-SB-001/?utm_source=x&amp;b=2&amp;a=1#top">'
    )
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001?a=1&b=2"


def test_a_page_url_in_a_non_canonical_spelling_is_still_the_same_host() -> None:
    html = head(f'<link rel="canonical" href="{H}/shop/p/HT-SB-001">')
    page = "HTTP://Halden.Test:80/shop/cutting/blades/p/HT-SB-001/"
    assert canonical_link(html, page) == f"{H}/shop/p/HT-SB-001"


def test_a_canonical_naming_the_page_itself_is_returned() -> None:
    html = head(f'<link rel="canonical" href="{PAGE}">')
    assert canonical_link(html, PAGE) == PAGE


@pytest.mark.parametrize(
    "rel",
    [
        "canonical alternate",
        "alternate canonical",
        "  canonical  ",
        "Canonical",
    ],
)
def test_canonical_is_found_among_several_rel_tokens(rel: str) -> None:
    """`rel` is a set of space-separated, ASCII case-insensitive tokens."""
    html = head(f'<link rel="{rel}" href="/shop/p/HT-SB-001">')
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001"


def test_the_first_canonical_wins() -> None:
    html = head(
        '<link rel="canonical" href="/shop/p/FIRST">',
        '<link rel="canonical" href="/shop/p/SECOND">',
    )
    assert canonical_link(html, PAGE) == f"{H}/shop/p/FIRST"


def test_an_unrelated_link_before_the_canonical_is_skipped() -> None:
    html = head(
        '<link rel="stylesheet" href="/static/site.css">',
        '<link rel="alternate" hreflang="de" href="/de/shop/p/HT-SB-001">',
        '<link rel="canonical" href="/shop/p/HT-SB-001">',
    )
    assert canonical_link(html, PAGE) == f"{H}/shop/p/HT-SB-001"


# ---------------------------------------------------------------------------
# canonical_link: what it refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href",
    [
        "https://elsewhere.test/p/HT-SB-001",
        # A subdomain is another host.
        "http://cdn.halden.test/shop/p/HT-SB-001",
        # Look-alikes: a suffix or prefix match would accept these.
        "http://xhalden.test/shop/p/HT-SB-001",
        "http://halden.test.elsewhere.test/shop/p/HT-SB-001",
        # Scheme-relative, to another host.
        "//elsewhere.test/shop/p/HT-SB-001",
    ],
)
def test_an_off_host_canonical_is_ignored(href: str) -> None:
    html = head(f'<link rel="canonical" href="{href}">')
    assert canonical_link(html, PAGE) is None


def test_a_canonical_on_another_scheme_is_ignored() -> None:
    """Scheme is part of identity (spec 004 §2 step 1 keeps it), so an
    `https` canonical on an `http` page is another URL, not this page's."""
    html = head('<link rel="canonical" href="https://halden.test/shop/p/HT-SB-001">')
    assert canonical_link(html, PAGE) is None


@pytest.mark.parametrize(
    "html",
    [
        "",
        head(),
        head('<link rel="stylesheet" href="/shop/p/HT-SB-001">'),
        head('<link rel="noncanonical" href="/shop/p/HT-SB-001">'),
        head('<link rel="canonicalish" href="/shop/p/HT-SB-001">'),
        head('<a rel="canonical" href="/shop/p/HT-SB-001">not a link element</a>'),
    ],
    ids=["no-html", "no-links", "other-rel", "noncanonical", "canonicalish", "anchor"],
)
def test_no_canonical_link_is_none(html: str) -> None:
    assert canonical_link(html, PAGE) is None


@pytest.mark.parametrize("href", ["", "   "])
def test_an_empty_canonical_is_none(href: str) -> None:
    """An empty `href` resolves to the page itself, which says nothing; it
    must not be read as the site's answer."""
    html = head(f'<link rel="canonical" href="{href}">')
    assert canonical_link(html, PAGE) is None


@pytest.mark.parametrize(
    "href",
    [
        "https://[object Object]/p",  # a templating bug, seen in the wild
        "http://halden.test:abc/x",
        "http://halden.test:99999/x",
        "http://[bad",
        "http://[::1/x",
    ],
)
def test_an_unparseable_canonical_is_none_not_a_crash(href: str) -> None:
    """A supplier's markup can say anything. Raising here crashes the page's
    crawl, which is then refetched until it fails with no observation; an
    unparseable canonical is no canonical."""
    html = head(f'<link rel="canonical" href="{href}">')
    assert canonical_link(html, PAGE) is None


def test_a_canonical_with_no_href_is_none() -> None:
    assert canonical_link(head('<link rel="canonical">'), PAGE) is None


def test_the_first_canonical_wins_even_when_it_is_off_host() -> None:
    """The site gave one answer; a second same-host `<link>` further down is
    not a fallback the crawler gets to pick."""
    html = head(
        '<link rel="canonical" href="https://elsewhere.test/p/HT-SB-001">',
        '<link rel="canonical" href="/shop/p/HT-SB-001">',
    )
    assert canonical_link(html, PAGE) is None


# ---------------------------------------------------------------------------
# Halden, through the served HTML
# ---------------------------------------------------------------------------

DISCS = f"{H}/shop/cutting/discs"


@pytest.fixture(scope="module")
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


@pytest.fixture(scope="module")
def get(site: FixtureSite) -> Callable[[str], str]:
    """GET a site-relative path as `halden.test`, over loopback. The promo's
    absolute spellings are built from the `Host` header."""

    def fetch(path: str) -> str:
        req = urllib.request.Request(f"{site.base_url}{path}", headers={"Host": HOST})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                body: bytes = r.read()
                return body.decode()
        except urllib.error.HTTPError as e:
            with e:
                raise AssertionError(f"{path} answered {e.code}") from e

    return fetch


@pytest.fixture(scope="module")
def promo(get: Callable[[str], str]) -> list[str]:
    root = LexborHTMLParser(get("/shop/"))
    hrefs = [a.attributes.get("href") or "" for a in root.css("section.promo a")]
    assert len(hrefs) >= 10, f"section.promo carries {len(hrefs)} spellings"
    return hrefs


def _absolute(href: str) -> str:
    return urljoin(f"{H}/shop/", href)


def test_every_promo_spelling_canonicalises_to_the_one_listing(promo: list[str]) -> None:
    """Acceptance: every `section.promo` spelling on `/shop/` is
    `http://halden.test/shop/cutting/discs`. Two spell something else on
    purpose: the unsorted pair keeps its filter (sorted), and `?page=2` is a
    different page."""
    expected = {
        DISCS,
        f"{DISCS}?colour=red&per_page=25",
        f"{DISCS}?page=2",
    }
    canonical = {href: canonical_url(_absolute(href)) for href in promo}
    assert set(canonical.values()) == expected, canonical

    # The exceptions, named: anything else that is not the bare listing is
    # a spelling canonicalisation failed to collapse.
    for href, url in canonical.items():
        keys = {k for k, _ in parse_qsl(urlsplit(href).query, keep_blank_values=True)}
        if "page" in keys:
            assert url == f"{DISCS}?page=2", href
        elif "colour" in keys:
            assert url == f"{DISCS}?colour=red&per_page=25", href
        else:
            assert url == DISCS, href


def test_the_unsorted_promo_pair_is_one_url(promo: list[str]) -> None:
    filtered = [h for h in promo if "colour=" in h]
    assert len(filtered) == 2 and filtered[0] != filtered[1], filtered
    assert len({canonical_url(_absolute(h)) for h in filtered}) == 1


def test_every_promo_spelling_is_already_canonical_once_canonicalised(promo: list[str]) -> None:
    for href in promo:
        once = canonical_url(_absolute(href))
        assert canonical_url(once) == once, href


def test_the_canonical_listing_is_fetchable(get: Callable[[str], str]) -> None:
    """Step 6 strips the slash Halden links with; the canonical form must
    still be a page, or canonicalising would turn every listing into a 404."""
    assert "product-card__link" in get("/shop/cutting/discs")


def test_a_blades_product_in_category_context_names_its_canonical(
    get: Callable[[str], str],
) -> None:
    path = "/shop/cutting/blades/p/HT-SB-001"
    assert canonical_link(get(path), f"{H}{path}") == f"{H}/shop/p/HT-SB-001"


def test_the_canonical_blades_product_names_itself(get: Callable[[str], str]) -> None:
    path = "/shop/p/HT-SB-001"
    assert canonical_link(get(path), f"{H}{path}") == f"{H}{path}"


def test_a_polish_products_off_host_canonical_is_ignored(get: Callable[[str], str]) -> None:
    path = "/shop/p/HT-PO-001"
    html = get(path)
    assert 'rel="canonical"' in html, "the polish no longer names a canonical"
    assert canonical_link(html, f"{H}{path}") is None
