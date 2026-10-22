"""Halden Tools, the discovery catalogue (BUILD_PLAN 2.1), pinned through the wire.

Every phase-2 task and the phase-2 exit test against this site, so each of
its shapes is asserted here over `FixtureSite` — from the HTML the server
actually serves, parsed with selectolax — never from `catalogue.py`'s tables.
The one exception is `PRODUCTS`: it is the list the phase-2 exit asserts
equality against, so it is the expected value, and the served site has to
reach exactly it.

A shape that quietly stops being served (a facet space that runs out, a trap
that ends, a mega-menu that becomes scoped) does not fail the phase-2 test
that relies on it; that test just passes for the wrong reason. These are what
fail instead.
"""

import re
import urllib.error
import urllib.request
import urllib.robotparser
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import pytest
from selectolax.lexbor import LexborHTMLParser

from tests.fixtures.catalogue import (
    EXIT_DISCOVERY,
    EXIT_PRODUCTS,
    EXIT_SEED,
    PARTNER_CARDS,
    PRODUCTS,
    products_under,
)
from tests.fixtures.server import FixtureSite

HOST = "halden.test"
ROOT = "/shop/"
DEEP = f"{ROOT}deep/"

# Spec 004 §3's default per-run URL cap. The facet space has to beat it on
# its own, or the cap is not what a facet-trap test is exercising.
URL_CAP = 20_000
# "Well past any cap": spec 004 §3's depth defaults are single digits.
TRAP_DEPTH = 50
# max_depth = 5 must provably stop before something reachable.
DEPTH_BEYOND_CAP = 6

# The discovery rules the product-set BFS uses: scoped tiles, product links
# and pagination. Facets and the mega-menu are deliberately not followed.
SCOPED_TILES = "section.subcategories a"
PRODUCT_LINKS = "a.product-card__link"
NEXT = 'a[rel="next"]'
FACETS = "form.facets a"
MEGA = "nav.mega a"


@dataclass(frozen=True)
class Page:
    status: int
    body: bytes

    @property
    def tree(self) -> LexborHTMLParser:
        return LexborHTMLParser(self.body.decode())


@pytest.fixture(scope="module")
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


@pytest.fixture(scope="module")
def get(site: FixtureSite) -> Callable[[str], Page]:
    """GET a site-relative path as `halden.test`, over loopback.

    The `Host` header is the invented host's, as a crawler's would be: the
    canonicalisation material is built from it.
    """

    def fetch(path: str) -> Page:
        req = urllib.request.Request(f"{site.base_url}{path}", headers={"Host": HOST})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return Page(r.status, r.read())
        except urllib.error.HTTPError as e:
            with e:
                return Page(e.code, e.read())

    return fetch


def _hrefs(page: Page, selector: str) -> list[str]:
    return [a.attributes.get("href") or "" for a in page.tree.css(selector)]


def _resolve(base: str, href: str) -> str:
    """`href` resolved against site-relative `base`, back to site-relative.

    Same-host absolute links are made relative so they can be fetched over
    loopback; anything off-host is returned absolute and never fetched.
    """
    absolute = urljoin(f"http://{HOST}{base}", href)
    parts = urlsplit(absolute)
    if parts.hostname != HOST or parts.port not in (None, 80):
        return absolute
    return urlunsplit(("", "", parts.path, parts.query, ""))


def _sorted_query(url: str) -> str:
    """The URL with its query sorted: two orders of one filter are one page."""
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(("", "", parts.path, query, ""))


@dataclass(frozen=True)
class ScopedCrawl:
    """What a tiles + products + pagination crawl from `/shop/` reaches."""

    depth: dict[str, int]  # every fetched URL → BFS depth
    pages: dict[str, Page]
    product_urls: set[str]


@pytest.fixture(scope="module")
def scoped(get: Callable[[str], Page]) -> ScopedCrawl:
    depth = {ROOT: 0}
    pages: dict[str, Page] = {}
    product_urls: set[str] = set()
    queue = deque([ROOT])
    while queue:
        url = queue.popleft()
        page = get(url)
        pages[url] = page
        assert page.status == 200, f"{url} is linked by a discovery rule and serves {page.status}"
        # A bound so a broken fixture fails here rather than hanging the suite.
        assert len(pages) < 1_000, "the scoped crawl is unbounded: a trap leaked into tiles"
        found = [
            *((h, False) for h in _hrefs(page, SCOPED_TILES)),
            *((h, False) for h in _hrefs(page, NEXT)),
            *((h, True) for h in _hrefs(page, PRODUCT_LINKS)),
        ]
        for href, is_product in found:
            target = _resolve(url, href)
            if not target.startswith("/"):
                continue  # off-host: never fetched, and not this site's product
            if is_product:
                product_urls.add(target)
            if target not in depth:
                depth[target] = depth[url] + 1
                queue.append(target)
    return ScopedCrawl(depth, pages, product_urls)


def _categories(scoped: ScopedCrawl) -> set[str]:
    """Category-tree nodes: listing pages reached through scoped tiles,
    excluding the depth chain, which is an archive and not a category."""
    nodes = set()
    for url, page in scoped.pages.items():
        for href in _hrefs(page, SCOPED_TILES):
            target = _resolve(url, href)
            if not target.startswith(DEEP):
                nodes.add(target)
    return nodes


def _children(get: Callable[[str], Page], path: str) -> list[str]:
    """Scoped-tile targets of `path`, less the depth chain: `/shop/cutting/`
    carries the archive tile on purpose, and it is not a subcategory."""
    tiles = [_resolve(path, h) for h in _hrefs(get(path), SCOPED_TILES)]
    return [t for t in tiles if not t.startswith(DEEP)]


# ---------------------------------------------------------------------------
# The product set
# ---------------------------------------------------------------------------


def test_the_scoped_crawl_reaches_exactly_the_product_set(scoped: ScopedCrawl) -> None:
    """The phase-2 exit's equality, proved possible: the served site, crawled
    by tiles + products + pagination with facets and mega-menu ignored,
    yields every SKU in `PRODUCTS` and nothing else."""
    assert len(PRODUCTS) == len(set(PRODUCTS)), "PRODUCTS repeats a SKU"

    urls_by_sku: dict[str, list[str]] = {}
    for url in scoped.product_urls:
        node = scoped.pages[url].tree.css_first(".product__sku")
        assert node is not None, f"{url} has no .product__sku"
        urls_by_sku.setdefault(node.text(strip=True), []).append(url)

    # One SKU at two URLs is allowed only as a canonical pair: every URL
    # names the same canonical.
    for sku, urls in urls_by_sku.items():
        if len(urls) > 1:
            canonicals = {_canonical(scoped.pages[u]) for u in urls}
            assert len(canonicals) == 1 and None not in canonicals, (
                f"{sku} is served at {urls}, which do not share a canonical"
            )

    skus = set(urls_by_sku)
    missing = set(PRODUCTS) - set(skus)
    extra = set(skus) - set(PRODUCTS)
    assert not missing, f"PRODUCTS not reachable from /shop/: {sorted(missing)}"
    assert not extra, f"reachable products not in PRODUCTS: {sorted(extra)}"


def test_every_product_page_extracts_with_a_selector_template(scoped: ScopedCrawl) -> None:
    for url in scoped.product_urls:
        tree = scoped.pages[url].tree
        title = tree.css_first("h1.product__title")
        price = tree.css_first(".product__price")
        assert title is not None and title.text(strip=True), f"{url}: no title"
        assert price is not None and any(c in price.text() for c in "£$€"), (
            f"{url}: price carries no currency"
        )
        images = [img.attributes.get("src") for img in tree.css("img.gallery__image")]
        assert images and all(images), f"{url}: no gallery images"


def test_the_canonical_product_url_is_shop_p_sku(get: Callable[[str], Page]) -> None:
    for sku in PRODUCTS:
        page = get(f"{ROOT}p/{sku}")
        assert page.status == 200, sku
        node = page.tree.css_first(".product__sku")
        assert node is not None and node.text(strip=True) == sku


def test_the_tree_is_three_categories_of_two_with_one_nest(
    get: Callable[[str], Page],
) -> None:
    categories = _children(get, ROOT)
    assert len(categories) == 3, categories

    nests = []
    for category in categories:
        subs = _children(get, category)
        assert len(subs) == 2, f"{category} has {subs}"
        nests += [s for s in subs if _children(get, s)]
    assert len(nests) == 1, f"expected exactly one subcategory nest, got {nests}"
    for grandchild in _children(get, nests[0]):
        assert not _children(get, grandchild), "the nest goes deeper than depth 3"
        assert get(grandchild).tree.css(PRODUCT_LINKS), f"{grandchild} is a leaf with no products"


# ---------------------------------------------------------------------------
# The phase-2 exit: a category seed under the operator's rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitCrawl:
    """What `EXIT_DISCOVERY` from `EXIT_SEED` reaches, applied by the letter."""

    depth: dict[str, int]  # every fetched URL → hop count from the seed
    pages: dict[str, Page]
    skus: set[str]
    offhost_products: set[str]  # product-rule hrefs on another host
    denied: list[str]  # same-host hrefs a deny pattern refused


@pytest.fixture(scope="module")
def exit_crawl(get: Callable[[str], Page]) -> ExitCrawl:
    """A deliberately literal reading of spec 004 §1's rules: the three
    selectors, `deny_patterns` searched against path+query, the host compared
    for equality (not suffix), and `max_depth` as a hop count from the seed.
    It stands in for 2.3's crawler so the fixture is proved *able* to give
    the exit its answer before that crawler exists."""
    rules = EXIT_DISCOVERY
    product_rule = str(rules["product_links"])
    selectors = [product_rule, str(rules["next_page"]), str(rules["subcategory_links"])]
    patterns, max_depth = rules["deny_patterns"], rules["max_depth"]
    assert isinstance(patterns, list) and isinstance(max_depth, int)
    deny = [re.compile(str(p)) for p in patterns]

    depth = {EXIT_SEED: 0}
    pages: dict[str, Page] = {}
    skus: set[str] = set()
    offhost: set[str] = set()
    denied: list[str] = []
    queue = deque([EXIT_SEED])
    while queue:
        url = queue.popleft()
        page = get(url)
        pages[url] = page
        assert page.status == 200, f"{url} is linked by an exit rule and serves {page.status}"
        # Without the deny pattern the facet space is in reach; fail, don't hang.
        assert len(pages) < 500, "the exit crawl is exploding: the deny pattern is not holding"
        sku = page.tree.css_first(".product__sku")
        if sku is not None:
            skus.add(sku.text(strip=True))
        for selector in selectors:
            for href in _hrefs(page, selector):
                absolute = urlsplit(urljoin(f"http://{HOST}{url}", href))
                if absolute.hostname != HOST or absolute.port not in (None, 80):
                    if selector == product_rule:
                        offhost.add(urlunsplit(absolute))
                    continue
                target = urlunsplit(("", "", absolute.path, absolute.query, ""))
                if any(p.search(target) for p in deny):
                    denied.append(target)
                    continue
                if target not in depth and depth[url] + 1 <= max_depth:
                    depth[target] = depth[url] + 1
                    queue.append(target)
    return ExitCrawl(depth, pages, skus, offhost, denied)


def test_the_exit_seed_yields_exactly_the_exit_products(exit_crawl: ExitCrawl) -> None:
    assert EXIT_PRODUCTS == products_under(EXIT_SEED)
    assert len(EXIT_PRODUCTS) == len(set(EXIT_PRODUCTS))
    missing = set(EXIT_PRODUCTS) - exit_crawl.skus
    extra = exit_crawl.skus - set(EXIT_PRODUCTS)
    assert not missing, f"the exit seed cannot reach {sorted(missing)}"
    assert not extra, f"the exit seed reaches products outside its subtree: {sorted(extra)}"


def test_the_exit_crawl_meets_every_partner_card_off_host(exit_crawl: ExitCrawl) -> None:
    """The exit's "without leaving the host" is only tested if leaving is on offer, in
    the container the product rule matches, including the look-alikes a
    suffix check would keep."""
    for card in PARTNER_CARDS:
        assert urlsplit(card).hostname != HOST, f"{card} is on-host"
    missing = set(PARTNER_CARDS) - exit_crawl.offhost_products
    assert not missing, f"the exit crawl never meets {sorted(missing)}"
    hosts = [urlsplit(c).hostname or "" for c in PARTNER_CARDS]
    assert any(h.endswith(HOST) and not h.endswith(f".{HOST}") for h in hosts), (
        "no look-alike a bare endswith(host) check would keep"
    )
    assert any(h.startswith(f"{HOST}.") for h in hosts), "no look-alike that starts with the host"
    assert any(h.endswith(f".{HOST}") for h in hosts), "no subdomain card"


def test_the_exit_rules_reach_a_facet_and_only_the_deny_pattern_stops_it(
    exit_crawl: ExitCrawl,
) -> None:
    facet_keys = {"colour", "grit", "sort", "per_page"}
    denied_facets = [
        u for u in exit_crawl.denied if facet_keys & {k for k, _ in parse_qsl(urlsplit(u).query)}
    ]
    assert denied_facets, "the exit rules never met a facet link, so the deny pattern is untested"
    fetched_facets = [
        u for u in exit_crawl.pages if facet_keys & {k for k, _ in parse_qsl(urlsplit(u).query)}
    ]
    assert not fetched_facets, f"faceted pages got past the deny pattern: {fetched_facets[:3]}"


def test_the_exit_depth_cap_reaches_deep_5_and_never_deep_6(exit_crawl: ExitCrawl) -> None:
    assert f"{DEEP}5/" in exit_crawl.pages, "max_depth 5 does not reach /shop/deep/5/"
    assert f"{DEEP}6/" not in exit_crawl.pages, "max_depth 5 reached /shop/deep/6/"
    assert f"{DEEP}6/" in _hrefs(exit_crawl.pages[f"{DEEP}5/"], SCOPED_TILES), (
        "/shop/deep/6/ is not linked from /5/, so the cap is not what stops it"
    )


def test_the_exit_crawl_discovers_both_urls_of_a_canonical_pair(exit_crawl: ExitCrawl) -> None:
    pairs = [
        (url, canonical)
        for url, page in exit_crawl.pages.items()
        if (canonical := _canonical(page)) is not None
        and canonical != url
        and canonical in exit_crawl.pages
    ]
    assert pairs, "no page in the exit crawl names a canonical the crawl also discovered"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def _paginated_leaf(scoped: ScopedCrawl) -> tuple[str, list[str]]:
    """A leaf spanning 3+ pages, and its pages in `rel=next` order."""
    for url, page in scoped.pages.items():
        if "?" in url or not page.tree.css(NEXT):
            continue
        chain = [url]
        while (nxt := _hrefs(scoped.pages[chain[-1]], NEXT)) and len(chain) < 50:
            chain.append(_resolve(chain[-1], nxt[0]))
        if len(chain) >= 3:
            return url, chain
    pytest.fail("no leaf spans three or more pages")


def test_a_leaf_spans_three_pages_and_the_last_has_no_next(scoped: ScopedCrawl) -> None:
    _, chain = _paginated_leaf(scoped)
    last = scoped.pages[chain[-1]]
    assert not last.tree.css(NEXT), "the last page links a next page"
    assert last.tree.css(PRODUCT_LINKS), "the last page lists nothing"


def test_pages_carry_numbered_links_and_page_2_is_a_different_page(
    scoped: ScopedCrawl,
) -> None:
    """`?page=2` is meaningful: canonicalisation must keep it, so the
    fixture has to make dropping it observable."""
    _, chain = _paginated_leaf(scoped)
    first, second = scoped.pages[chain[0]], scoped.pages[chain[1]]
    numbered = [a.text(strip=True) for a in first.tree.css("nav.pagination a")]
    assert {"2", "3"} <= set(numbered), f"page 1 has no numbered page links: {numbered}"
    assert "page=2" in chain[1]
    assert set(_hrefs(first, PRODUCT_LINKS)).isdisjoint(_hrefs(second, PRODUCT_LINKS))


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------


def _first_leaf(scoped: ScopedCrawl) -> str:
    for url, page in scoped.pages.items():
        if "?" not in url and page.tree.css(FACETS):
            return url
    pytest.fail("no listing page carries facet links")


def test_facet_links_add_to_the_current_query_and_change_nothing(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    leaf = _first_leaf(scoped)
    base = scoped.pages[leaf]
    first = _resolve(leaf, _hrefs(base, FACETS)[0])
    chosen = set(parse_qsl(urlsplit(first).query))
    faceted = get(first)
    assert faceted.status == 200

    for href in _hrefs(faceted, FACETS):
        query = set(parse_qsl(urlsplit(_resolve(first, href)).query))
        assert chosen < query and len(query - chosen) == 1, (
            f"facet link {href} does not add one value to {chosen}"
        )
    assert _hrefs(faceted, PRODUCT_LINKS) == _hrefs(base, PRODUCT_LINKS), (
        "a faceted page lists different products; the trap must look like a working filter"
    )
    names = {k for href in _hrefs(base, FACETS) for k, _ in parse_qsl(urlsplit(href).query)}
    assert {"colour", "grit", "sort", "per_page"} <= names, names


def test_the_facet_space_alone_exceeds_the_url_cap(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    """Following only facet links from one leaf, breadth-first, the distinct
    hrefs discovered pass 20,000 before the space runs out.

    Stopped the moment the count passes the cap: the claim is how many URLs
    exist, not how many a test can afford to fetch. The next test closes the
    gap this one leaves — hrefs that differ only in query order.
    """
    start = _first_leaf(scoped)
    seen = {start}
    queue = deque([start])
    while queue and len(seen) <= URL_CAP:
        url = queue.popleft()
        page = get(url)
        assert page.status == 200, url
        for href in _hrefs(page, FACETS):
            target = _resolve(url, href)
            if target not in seen:
                seen.add(target)
                queue.append(target)
    assert len(seen) > URL_CAP, f"the facet space ran out at {len(seen)} URLs"


def test_every_facet_combination_is_reachable_so_order_does_not_shrink_it(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    """2.2 sorts queries, so to the cap two orders of one filter are one URL.

    The space survives that if every faceted page offers every value not yet
    chosen: then every *subset* of the values is reachable, 2^n distinct
    sorted URLs. Walked to the bottom of the lattice — every value chosen —
    checking the offer at each step, which a cap on selections fails.
    """
    url = _first_leaf(scoped)
    offered = {pair for h in _hrefs(get(url), FACETS) for pair in parse_qsl(urlsplit(h).query)}
    assert 2 ** len(offered) > URL_CAP, f"{len(offered)} facet values make too few subsets"

    chosen: set[tuple[str, str]] = set()
    while chosen != offered:
        page = get(url)
        assert page.status == 200, url
        hrefs = _hrefs(page, FACETS)
        here = {pair for h in hrefs for pair in parse_qsl(urlsplit(h).query) if pair not in chosen}
        assert here == offered - chosen, (
            f"with {len(chosen)} chosen, {url} no longer offers {sorted(offered - chosen - here)}"
        )
        # Any link will do: each adds one value, so the walk ends with all.
        url = _resolve(url, hrefs[-1])
        chosen = set(parse_qsl(urlsplit(url).query))
    assert get(url).status == 200


# ---------------------------------------------------------------------------
# Mega-menu, scoped tiles, hidden tiles
# ---------------------------------------------------------------------------


def test_the_mega_menu_on_a_leaf_product_page_links_every_category(
    scoped: ScopedCrawl,
) -> None:
    tree = _categories(scoped)
    assert tree, "the scoped crawl found no categories"
    product = sorted(scoped.product_urls)[0]
    mega = {_resolve(product, h) for h in _hrefs(scoped.pages[product], MEGA)}
    assert tree <= mega, f"the mega-menu misses {sorted(tree - mega)}"


def test_the_mega_menu_is_on_every_listing_page_too(scoped: ScopedCrawl) -> None:
    """So a `nav a` rule discovers the whole tree from depth 0."""
    tree = _categories(scoped)
    for url, page in scoped.pages.items():
        if url in scoped.product_urls:
            continue
        mega = {_resolve(url, h) for h in _hrefs(page, MEGA)}
        assert tree <= mega, f"{url}'s mega-menu misses {sorted(tree - mega)}"


def test_a_category_pages_scoped_tiles_link_only_its_children(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    tree = _categories(scoped)
    categories = [c for c in _children(get, ROOT) if c in tree]
    assert categories
    for category in categories:
        children = _children(get, category)
        assert children, f"{category} has no scoped tiles"
        for child in children:
            rest = child.removeprefix(category)
            assert child.startswith(category) and rest.count("/") == 1, (
                f"{category}'s scoped tiles link {child}, which is not its child"
            )
        mega = {_resolve(category, h) for h in _hrefs(get(category), MEGA)}
        assert set(children) < mega, "the scoped tiles are not narrower than the mega-menu"


def test_exactly_one_category_hides_its_tiles_with_display_none(
    get: Callable[[str], Page],
) -> None:
    """Spec 004 §3a case A: the links are in the static HTML, inside a
    `display:none` container. No JavaScript involved."""
    hidden = []
    for category in _children(get, ROOT):
        page = get(category)
        for section in page.tree.css("section.subcategories"):
            style = (section.attributes.get("style") or "").replace(" ", "").lower()
            if "display:none" in style:
                hidden.append(category)
                assert section.css("a"), f"{category} hides an empty container"
        assert not page.tree.css("script"), f"{category} uses script"
    assert len(hidden) == 1, f"expected one hidden-tiles category, got {hidden}"


# ---------------------------------------------------------------------------
# Canonical
# ---------------------------------------------------------------------------


def _canonical(page: Page) -> str | None:
    link = page.tree.css_first('link[rel="canonical"]')
    return None if link is None else link.attributes.get("href")


def test_a_product_in_category_context_names_the_canonical_url(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    context = [u for u in scoped.product_urls if not u.startswith(f"{ROOT}p/")]
    assert context, "no product is linked at a category-context URL"
    for url in context:
        sku = url.rstrip("/").rsplit("/", 1)[1]
        canonical_url = f"{ROOT}p/{sku}"
        here, there = get(url), get(canonical_url)
        assert here.status == 200 and there.status == 200
        assert _canonical(here) == canonical_url, url
        assert _canonical(there) == canonical_url, canonical_url


def test_one_product_names_an_off_host_canonical(scoped: ScopedCrawl) -> None:
    offhost = []
    for url in scoped.product_urls:
        href = _canonical(scoped.pages[url])
        if href is not None and urlsplit(urljoin(f"http://{HOST}/", href)).netloc != HOST:
            offhost.append(url)
    assert offhost, "no product page names an off-host canonical for 2.2 to ignore"


# ---------------------------------------------------------------------------
# Canonicalisation material and rejects
# ---------------------------------------------------------------------------


def _collapse(path: str) -> str:
    while "//" in path:
        path = path.replace("//", "/")
    return path if path.endswith("/") else path + "/"


def test_the_promo_spells_one_listing_many_ways(get: Callable[[str], Page]) -> None:
    root = get(ROOT)
    hrefs = _hrefs(root, "section.promo a")
    assert hrefs, "no section.promo on /shop/"

    queries = [dict(parse_qsl(urlsplit(h).query)) for h in hrefs]
    keys = {k for q in queries for k in q}
    assert {"utm_source", "gclid", "ref", "page"} <= keys, keys
    assert any("#" in h for h in hrefs), "no fragment"
    assert any("/./" in h or "/../" in h for h in hrefs), "no dot segments"
    assert any("//" in urlsplit(h).path for h in hrefs), "no duplicate slash"
    paths = {urlsplit(h).path for h in hrefs if not urlsplit(h).netloc}
    assert any(p + "/" in paths for p in paths), "no with/without trailing-slash pair"
    raw_queries = [urlsplit(h).query for h in hrefs if urlsplit(h).query]
    assert any(
        a != b and sorted(parse_qsl(a)) == sorted(parse_qsl(b))
        for a in raw_queries
        for b in raw_queries
    ), "no unsorted-query pair"
    assert any(h.startswith(f"http://{HOST.upper()}:80/") for h in hrefs), (
        "no absolute same-host link with an upper-case host and the default port"
    )

    # Every spelling, once canonicalised, is the one listing; ?page=2 is not.
    targets = {_collapse(urlsplit(_resolve(ROOT, h)).path) for h in hrefs}
    assert len(targets) == 1, targets
    listing = targets.pop()
    page_one = _hrefs(get(listing), PRODUCT_LINKS)
    page_two = _hrefs(get(f"{listing}?page=2"), PRODUCT_LINKS)
    assert page_one and page_two and page_one != page_two


def test_the_footer_carries_every_reject(get: Callable[[str], Page]) -> None:
    hrefs = _hrefs(get(ROOT), "footer.site-footer a")
    hosts = {urlsplit(h).netloc.lower() for h in hrefs}
    schemes = {urlsplit(h).scheme.lower() for h in hrefs}

    assert any(h and h != HOST and not h.endswith(f".{HOST}") for h in hosts), "no off-host"
    assert any(h.endswith(f".{HOST}") for h in hosts), "no subdomain link"
    assert {"mailto", "tel", "javascript"} <= schemes, schemes
    assert any(len(urljoin(f"http://{HOST}/", h)) > 2_000 for h in hrefs), "no long URL"
    assert any(urlsplit(h).path.startswith(f"{ROOT}news/") for h in hrefs), "no calendar"
    assert any(urlsplit(h).path.startswith(f"{ROOT}loop/") for h in hrefs), "no loop"


def test_the_rejects_footer_is_on_a_leaf_listing_too(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    """A category seed never sees the root, so the rejects must be on the
    pages it does see."""
    leaf = _first_leaf(scoped)
    hrefs = _hrefs(get(leaf), "footer.site-footer a")
    schemes = {urlsplit(h).scheme.lower() for h in hrefs}
    assert {"mailto", "tel", "javascript"} <= schemes, f"{leaf}'s footer has {schemes}"
    assert any(urlsplit(h).hostname not in (None, HOST) for h in hrefs), (
        f"{leaf}'s footer has no off-host link"
    )


def test_halden_answers_with_the_permissive_robots_file(get: Callable[[str], Page]) -> None:
    page = get("/robots.txt")
    assert page.status == 200
    robots = urllib.robotparser.RobotFileParser()
    robots.parse(page.body.decode().splitlines())
    assert robots.can_fetch("Spydra", f"http://{HOST}{ROOT}cutting/discs/")


# ---------------------------------------------------------------------------
# Depth and the three traps
# ---------------------------------------------------------------------------


def test_the_depth_chain_reaches_past_a_depth_5_cap(scoped: ScopedCrawl) -> None:
    deepest = max(scoped.depth, key=lambda u: scoped.depth[u])
    assert scoped.depth[deepest] >= DEPTH_BEYOND_CAP, f"deepest is {deepest}"
    assert scoped.pages[deepest].status == 200

    # Provably out of reach: no page shallower than its parent links it by
    # any anchor at all, so no rule could shortcut to it.
    for url, page in scoped.pages.items():
        if scoped.depth[url] < scoped.depth[deepest] - 1:
            linked = {_resolve(url, h) for h in _hrefs(page, "a")}
            assert deepest not in linked, f"{url} shortcuts to {deepest}"


def _follow(get: Callable[[str], Page], start: str, selector: str) -> list[str]:
    """`TRAP_DEPTH` hops from `start`, each to a URL not seen before."""
    chain = [start]
    for _ in range(TRAP_DEPTH):
        page = get(chain[-1])
        assert page.status == 200, f"{chain[-1]} at hop {len(chain)} serves {page.status}"
        linked = [_resolve(chain[-1], h) for h in _hrefs(page, selector)]
        new = [u for u in linked if u not in chain]
        assert new, f"the trap ended after {len(chain)} hops at {chain[-1]}"
        chain.append(new[0])
    return chain


def test_the_repeating_relative_link_never_ends(get: Callable[[str], Page]) -> None:
    footer = _hrefs(get(ROOT), "footer.site-footer a")
    start = next(_resolve(ROOT, h) for h in footer if urlsplit(h).path.startswith(f"{ROOT}loop/"))
    loop_href = _hrefs(get(start), SCOPED_TILES)
    assert loop_href and not loop_href[0].startswith("/"), "the loop's link is not relative"
    chain = _follow(get, start, SCOPED_TILES)
    assert chain[-1].count("loop/x/") > TRAP_DEPTH


def test_the_loop_repeats_even_when_the_base_loses_its_trailing_slash(
    get: Callable[[str], Page],
) -> None:
    """2.2 strips trailing slashes before the base is used to resolve a
    relative link. The trap must survive that, or 2.5 is testing nothing."""
    footer = _hrefs(get(ROOT), "footer.site-footer a")
    url = next(_resolve(ROOT, h) for h in footer if urlsplit(h).path.startswith(f"{ROOT}loop/"))
    for hop in range(TRAP_DEPTH):
        page = get(url)
        assert page.status == 200, f"{url} at hop {hop} serves {page.status}"
        hrefs = _hrefs(page, SCOPED_TILES)
        assert hrefs, f"the loop ended at {url}"
        following = _resolve(url.rstrip("/"), hrefs[0])
        assert following.count("loop/x/") == url.count("loop/x/") + 1, (
            f"{url} → {following} does not add a loop/x/ pair"
        )
        url = following


def test_the_news_calendar_never_ends(get: Callable[[str], Page]) -> None:
    footer = _hrefs(get(ROOT), "footer.site-footer a")
    start = next(_resolve(ROOT, h) for h in footer if urlsplit(h).path.startswith(f"{ROOT}news/"))
    _follow(get, start, NEXT)


def test_the_trap_never_ends(get: Callable[[str], Page]) -> None:
    _follow(get, "/trap/", "a")


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


def test_every_page_is_byte_identical_across_fetches(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    leaf = _first_leaf(scoped)
    faceted = _resolve(leaf, _hrefs(scoped.pages[leaf], FACETS)[0])
    urls = [*scoped.pages, faceted, f"{ROOT}loop/x/loop/x/page", f"{ROOT}news/2026/10/"]
    for url in urls:
        first, second = get(url), get(url)
        assert first.status == 200, url
        assert first.body == second.body, f"{url} changed between two fetches"


def test_a_path_with_and_without_its_trailing_slash_is_one_page(
    scoped: ScopedCrawl, get: Callable[[str], Page]
) -> None:
    leaf = _first_leaf(scoped)
    product = f"{ROOT}p/{PRODUCTS[0]}"
    for slashed in (ROOT, leaf, f"{product}/"):
        bare = slashed.rstrip("/")
        a, b = get(slashed), get(bare)
        assert a.status == b.status == 200, slashed
        assert a.body == b.body, f"{slashed} and {bare} differ"


@pytest.mark.parametrize(
    "path",
    [
        "/shop/nope/",
        "/shop/cutting/nope/",
        "/shop/p/HT-NOPE-001",
        "/shop/deep/nope/",
        "/shop/news/2026/13/",
        "/shop/cutting/blades/p/HT-CD-001",
    ],
)
def test_an_unknown_shop_path_is_a_404(get: Callable[[str], Page], path: str) -> None:
    assert get(path).status == 404
