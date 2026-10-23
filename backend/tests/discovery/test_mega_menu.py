"""`whole_tree()`: the mega-menu guard, tested against Halden's served pages
(spec 004 §3a, §5; BUILD_PLAN 2.6).

Every discovery goes through `discover` over the fixture site as
`halden.test`, the way the dry-run (2.10) will call it; `whole_tree` is the
analysis whose finding the dry-run renders. The numbers the contract derives
— 11 links, 3 spanning branches, a deepest chain of 3 — are computed from
`catalogue.py`'s tree here, never written as literals, so a catalogue that
grows a category moves these tests with it.

The guard's whole point is what stays **silent**: scoped tiles over the same
pages that fire under `nav a` (counting plain roots instead of spanning
roots would fire on every two-tile container — that inversion is the
mutation this suite exists to catch), the exit rules on the exit seed, and
facet spellings of one page. The single-spanning-root blind spot is
deliberate (task 2.6 "Decided"): a menu nested under one top-level branch is
§3a's "prefer the path already in the crawl" projection, which 2.10 owns.
"""

import ast
import inspect
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest

from spydra.discovery import mega_menu as mega_menu_module
from spydra.discovery.links import Discovery, discover
from spydra.discovery.mega_menu import whole_tree
from spydra.domain.entities import DiscoveryRules
from spydra.domain.urls import canonical_url
from tests.fixtures.catalogue import (
    DEEP_PREFIX,
    EXIT_DISCOVERY,
    EXIT_SEED,
    FACETS,
    HOST,
    NODES,
    PREFIX,
    TREE,
)
from tests.fixtures.server import FixtureSite

BASE = f"http://{HOST}"
MAX_DEPTH = 5

# The pages these tests discover. A category page carries the mega-menu and
# no pagination, so `nav a` there matches exactly the mega links.
CUTTING = TREE[0].path
GRINDING_BELTS = TREE[1].children[1].path
FINISHING = TREE[2].path
DISCS = TREE[0].children[0].path
ROOT = PREFIX
SCOPED = "section.subcategories a"


def _canon(site_path: str) -> str:
    """The canonical path of a site-relative catalogue path."""
    return urlsplit(canonical_url(f"{BASE}{site_path}")).path


def _canon_of(found: Discovery) -> set[str]:
    return {urlsplit(canonical_url(url)).path for url, _ in found.accepted["subcategory_links"]}


# The mega-menu links every category node once, so its accepted links and
# distinct paths are the node count, and its spanning roots are the top
# categories. The deepest ancestor→descendant chain is the deepest node:
# grinding → belts → narrow (node paths end in "/", so one node's path
# starting with another's is a whole segment).
MEGA_LINKS = len(NODES)
BRANCHES = len(TREE)
LEVELS = 1 + max(
    sum(node.path != other.path and node.path.startswith(other.path) for other in NODES)
    for node in NODES
)
BRANCH_SAMPLE = tuple(sorted(_canon(n.path) for n in TREE))
# Scoped tiles on the pages used below: the exit seed also carries the
# archive tile, which is not a subcategory but is a root like any other.
CUTTING_TILES = (*(_canon(n.path) for n in TREE[0].children), _canon(f"{DEEP_PREFIX}1/"))
ROOT_TILES = tuple(_canon(n.path) for n in TREE)


@pytest.fixture(scope="module")
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


@pytest.fixture(scope="module")
def get(site: FixtureSite) -> Callable[[str], str]:
    """The served HTML of a site-relative path, requested as `halden.test`."""

    def fetch(path: str) -> str:
        req = urllib.request.Request(f"{site.base_url}{path}", headers={"Host": HOST})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body: bytes = resp.read()
        return body.decode()

    return fetch


def run(
    get: Callable[[str], str],
    path: str,
    rules: DiscoveryRules,
    *,
    html: str | None = None,
) -> Discovery:
    return discover(
        get(path) if html is None else html,
        BASE + path,
        rules,
        host=HOST,
        depth=0,
        max_depth=MAX_DEPTH,
    )


def exit_rules() -> DiscoveryRules:
    """`EXIT_DISCOVERY` as the template codec would read it (2.3's helper)."""
    raw = EXIT_DISCOVERY
    return DiscoveryRules(
        product_links=str(raw["product_links"]),
        next_page=str(raw["next_page"]),
        subcategory_links=str(raw["subcategory_links"]),
        deny_patterns=tuple(cast(list[str], raw["deny_patterns"])),
    )


# ---------------------------------------------------------------------------
# It fires (spec 004 §5: "caught by the dry-run as discovering the whole
# tree at depth 0")
# ---------------------------------------------------------------------------


def test_a_nav_rule_over_the_mega_menu_finds_the_whole_tree(
    get: Callable[[str], str],
) -> None:
    """Spec 004 §3a's hazard, on a real page: `nav a` on a category page
    accepts the mega-menu's every node — categories and their own
    subcategories under all three branches, the deepest chain three nodes
    deep. The finding's numbers, derived from the catalogue, are what the
    dry-run report (2.10) will carry."""
    finding = whole_tree(run(get, CUTTING, DiscoveryRules(subcategory_links="nav a")))

    assert finding is not None
    assert finding.links == MEGA_LINKS
    assert finding.paths == MEGA_LINKS
    assert finding.branches == BRANCHES
    assert finding.levels == LEVELS
    assert finding.roots == BRANCH_SAMPLE


def test_query_spellings_of_one_page_do_not_inflate_the_tree(
    get: Callable[[str], str],
) -> None:
    """The root's promo spells the discs listing eleven ways. Under a rule
    that matches the menu **and** the promo, the accepted links include two
    query spellings of a page the menu already links — they must collapse
    into the one node, or a facet-shaped page could fake links and paths the
    tree does not have."""
    promo = run(get, ROOT, DiscoveryRules(subcategory_links="section.promo a"))
    promo_links = promo.accepted["subcategory_links"]
    promo_paths = _canon_of(promo)
    assert len(promo_links) > 1 and len(promo_paths) == 1, "the promo no longer spells one page"

    finding = whole_tree(run(get, ROOT, DiscoveryRules(subcategory_links="nav a, section.promo a")))

    assert finding is not None
    assert finding.paths == MEGA_LINKS, "query spellings and duplicates became nodes"
    assert finding.links == MEGA_LINKS + len(promo_links) - len(promo_paths)
    assert finding.branches == BRANCHES
    assert finding.levels == LEVELS
    assert finding.roots == BRANCH_SAMPLE


# ---------------------------------------------------------------------------
# It stays silent (the false positive this task exists to prevent)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "tiles"),
    [(CUTTING, CUTTING_TILES), (ROOT, ROOT_TILES)],
    ids=["exit-seed", "shop-root"],
)
def test_scoped_tiles_on_the_same_pages_stay_silent(
    get: Callable[[str], str], path: str, tiles: tuple[str, ...]
) -> None:
    """`section.subcategories` over the very page `nav a` fires on: one
    container's tiles, several roots, none spanning — a parent whose children
    are all in the set is what "spanning" requires, and no tile here has a
    child. Counting plain roots instead would fire on exactly this shape."""
    found = run(get, path, DiscoveryRules(subcategory_links=SCOPED))

    assert _canon_of(found) == set(tiles)
    assert len(tiles) >= 2, "the counterexample lost its multiple roots"
    assert whole_tree(found) is None


def test_scoped_tiles_on_a_page_that_also_carries_the_mega_menu_stay_silent(
    get: Callable[[str], str],
) -> None:
    """/shop/grinding/belts/ carries both menus: `nav a` on it is the whole
    tree (the precondition, asserted), while its own tiles are narrow and
    wide — two roots, neither spanning. This is the plain-roots near-shape."""
    assert whole_tree(run(get, GRINDING_BELTS, DiscoveryRules(subcategory_links="nav a")))

    found = run(get, GRINDING_BELTS, DiscoveryRules(subcategory_links=SCOPED))

    assert _canon_of(found) == {_canon(n.path) for n in TREE[1].children[1].children}
    assert whole_tree(found) is None


def test_the_exit_rules_on_the_exit_seed_stay_silent(
    get: Callable[[str], str],
) -> None:
    """The production rule set (tiles + facets) on `EXIT_SEED`: a non-leaf
    page renders no facets, so the subcategory rule keeps the three flat
    tiles and the guard has nothing to say."""
    found = run(get, EXIT_SEED, exit_rules())

    assert _canon_of(found) == set(CUTTING_TILES)
    assert whole_tree(found) is None


def test_a_menu_narrowed_to_one_branch_stays_silent(
    get: Callable[[str], str],
) -> None:
    """The deliberate blind spot, pinned (task 2.6 "Decided"): a site-wide
    menu nested under a single top-level branch — here the grinding subtree
    off the same mega-menu — has one spanning root, and structure cannot
    distinguish it from one section's tiles. §3a's projection in the dry-run
    (2.10) is the backstop, not this analysis."""
    grinding = tuple(n for n in NODES if n.path.startswith(f"{PREFIX}grinding"))
    assert len(grinding) > 2, "the grinding branch lost its subtree"

    found = run(
        get, CUTTING, DiscoveryRules(subcategory_links='nav.mega a[href^="/shop/grinding"]')
    )

    assert len(found.accepted["subcategory_links"]) == len(grinding)
    assert whole_tree(found) is None


def test_a_menu_narrowed_to_two_branches_still_fires(
    get: Callable[[str], str],
) -> None:
    """`allow_patterns` that narrow the mega-menu to cutting and grinding
    leave two spanning branches: still a multi-branch menu, still flagged —
    and the operator sample names exactly the two branches that leaked."""
    two = tuple(
        n
        for n in NODES
        if n.path.startswith(f"{PREFIX}cutting") or n.path.startswith(f"{PREFIX}grinding")
    )
    assert len(two) < MEGA_LINKS, "the allow patterns no longer narrow anything"

    finding = whole_tree(
        run(
            get,
            CUTTING,
            DiscoveryRules(
                subcategory_links="nav a", allow_patterns=(r"^/shop/(cutting|grinding)",)
            ),
        )
    )

    assert finding is not None
    assert finding.paths == len(two)
    assert finding.branches == 2
    assert finding.roots == (_canon(TREE[0].path), _canon(TREE[1].path))


def test_a_product_rule_matching_the_menu_is_not_this_guard_to_flag(
    get: Callable[[str], str],
) -> None:
    """The analysis reads only `subcategory_links` (spec 004 §3a names the
    rule). A product rule matching a nav is a broken selector the count and
    sample report already exposes — flagging it here would be a second
    implementation of that report."""
    found = run(get, CUTTING, DiscoveryRules(product_links="nav a"))

    assert len(found.accepted["product_links"]) == MEGA_LINKS
    assert not found.accepted.get("subcategory_links")
    assert whole_tree(found) is None


def test_a_bare_string_prefix_is_not_an_ancestor(get: Callable[[str], str]) -> None:
    """/shop/cutting vs /shop/cutting-tools: a string prefix, not a path
    ancestor. Two tiles spliced into the root's container alongside the
    category tiles make five roots with no parent among them; if the
    boundary were bare `startswith`, cutting and grinding would "span" their
    -tools spellings and this flat tile set would fire."""
    served = get(ROOT)
    marker = '<section class="subcategories">'
    assert served.count(marker) == 1, "the root's tile container changed; the splice missed"
    spliced = served.replace(
        marker,
        marker
        + '<a class="subcategory-tile" href="/shop/cutting-tools/">Cutting tools</a>'
        + '<a class="subcategory-tile" href="/shop/grinding-tools/">Grinding tools</a>',
        1,
    )

    found = run(get, ROOT, DiscoveryRules(subcategory_links=SCOPED), html=spliced)

    assert _canon_of(found) == {*ROOT_TILES, "/shop/cutting-tools", "/shop/grinding-tools"}
    assert whole_tree(found) is None


def test_facet_spellings_of_one_page_cannot_fake_a_tree(
    get: Callable[[str], str],
) -> None:
    """Every facet link on a leaf page is the same page with a different
    query: one value per facet not yet chosen, the full set on page one.
    Sixteen accepted links, one canonical path — no nesting to build a
    branch on, however many spellings the site offers."""
    found = run(get, DISCS, DiscoveryRules(subcategory_links="form.facets a"))

    links = found.accepted["subcategory_links"]
    assert len(links) == sum(len(values) for values in FACETS.values())
    assert _canon_of(found) == {_canon(DISCS)}
    assert whole_tree(found) is None


# ---------------------------------------------------------------------------
# Case A: display:none tiles, discovered statically (spec 004 §3a, §5)
# ---------------------------------------------------------------------------


def test_css_hidden_tiles_are_discovered_by_the_static_fetch(
    get: Callable[[str], str],
) -> None:
    """Spec 004 §5: "a fixture whose subcategory links are `display:none` is
    discovered by a static fetch with no reveal step". The served bytes
    carry the hidden container (the precondition — selectolax computes no
    styles, so a CSS-hidden link is an ordinary match), and `discover`
    accepts both tiles."""
    served = get(FINISHING)
    assert '<section class="subcategories" style="display:none">' in served, (
        "the hidden-tiles container is not display:none in the served bytes"
    )

    found = run(get, FINISHING, DiscoveryRules(subcategory_links=SCOPED))

    assert _canon_of(found) == {_canon(n.path) for n in TREE[2].children}
    assert [(urlsplit(url).path, depth) for url, depth in found.accepted["subcategory_links"]] == [
        (n.path, 1) for n in TREE[2].children
    ]
    assert whole_tree(found) is None


# ---------------------------------------------------------------------------
# Pure (2.3's house style)
# ---------------------------------------------------------------------------

_IO_MODULES = (
    "spydra.adapters",
    "spydra.ports",
    "spydra.observations",
    "spydra.scheduler",
    "sqlalchemy",
    "asyncpg",
    "httpx",
    "httpx2",
    "socket",
    "urllib.request",
)


def test_whole_tree_imports_nothing_that_could_write() -> None:
    """The dry-run (2.10) shares this analysis, and an analysis that wrote
    would not be one a dry-run could call. Checked on the module's imports,
    as `test_links.py` checks `discover`."""
    source = Path(inspect.getfile(mega_menu_module)).read_text()
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offending = [m for m in imported if any(m == p or m.startswith(p + ".") for p in _IO_MODULES)]
    assert offending == []
    assert not inspect.iscoroutinefunction(whole_tree)


def test_whole_tree_requests_nothing_and_gives_the_same_answer_twice(
    get: Callable[[str], str], site: FixtureSite
) -> None:
    html = get(CUTTING)
    before = len(site.requests)

    found = run(get, CUTTING, DiscoveryRules(subcategory_links="nav a"), html=html)
    first = whole_tree(found)
    second = whole_tree(found)

    assert len(site.requests) == before, "whole_tree fetched something"
    assert first is not None
    assert first == second
