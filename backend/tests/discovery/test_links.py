"""`discover()`: what a page leads to, and why every other link was dropped
(spec 004 §1, §4; BUILD_PLAN 2.3).

**Against Halden's served pages, not markup written for the test.** Every
page is fetched from the fixture site over loopback as `halden.test`, the
way the crawler sees it, and `discover` is called with that host. That is
what makes the partner cards' look-alikes (`xhalden.test`,
`halden.test.elsewhere.test`) a real test of the same-host rule rather than
a trivially different port.

The one exception is the unparseable test, which appends two broken hrefs
to a served page: Halden has none, and adding them to the catalogue's
footer would change every listing page for every other suite.

Expected values come from the catalogue (`catalogue.py`), not from running
`discover`: discs page 1 lists `HT-CD-001`..`010`, then the four partner
cards; its facet form links one value per facet not yet chosen; and so on.
"""

import ast
import inspect
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest

from spydra.discovery import links as links_module
from spydra.discovery.links import Discovery, Rejected, RejectReason, discover
from spydra.domain.entities import DiscoveryRules
from tests.fixtures.catalogue import (
    DEEP_PREFIX,
    EXIT_DISCOVERY,
    EXIT_SEED,
    FACETS,
    HOST,
    PARTNER_CARDS,
)
from tests.fixtures.server import FixtureSite

BASE = f"http://{HOST}"
DISCS = "/shop/cutting/discs/"
ROOT = "/shop/"
MAX_DEPTH = 5


def exit_rules() -> DiscoveryRules:
    """`EXIT_DISCOVERY` as the template codec would read it. Its
    `max_depth` key is the domain's, not the template's (task "Decided"),
    so it is passed to `discover` separately."""
    raw = EXIT_DISCOVERY
    return DiscoveryRules(
        product_links=str(raw["product_links"]),
        next_page=str(raw["next_page"]),
        subcategory_links=str(raw["subcategory_links"]),
        deny_patterns=tuple(cast(list[str], raw["deny_patterns"])),
    )


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
    depth: int = 0,
    max_depth: int = MAX_DEPTH,
    domain_deny: tuple[str, ...] = (),
    html: str | None = None,
) -> Discovery:
    return discover(
        get(path) if html is None else html,
        BASE + path,
        rules,
        host=HOST,
        depth=depth,
        max_depth=max_depth,
        domain_deny=domain_deny,
    )


def rejected(found: Discovery, reason: RejectReason) -> Rejected | None:
    """The tally for one non-pattern reason, however it is keyed."""
    hits = [r for r in found.rejected.values() if r.reason is reason]
    assert len(hits) <= 1, f"{reason} tallied under {len(hits)} keys"
    return hits[0] if hits else None


def denied(found: Discovery) -> dict[str, int]:
    """Deny-pattern rejects, pattern → count."""
    return {
        str(r.pattern): r.count
        for r in found.rejected.values()
        if r.reason is RejectReason.DENY_PATTERN
    }


def paths(urls: Iterable[str]) -> list[str]:
    """Path (slash-insensitive) plus query of each URL, for asserting on
    samples whose exact spelling is not the point."""
    out = []
    for url in urls:
        parts = urlsplit(url)
        p = parts.path.rstrip("/") or "/"
        out.append(f"{p}?{parts.query}" if parts.query else p)
    return out


def products(*numbers: int, depth: int = 1) -> tuple[tuple[str, int], ...]:
    return tuple((f"{BASE}/shop/p/HT-CD-{n:03d}", depth) for n in numbers)


# ---------------------------------------------------------------------------
# Per-rule groups, per-reason rejects (spec 004 §4's shape)
# ---------------------------------------------------------------------------


def test_a_leaf_listing_groups_what_it_keeps_by_rule(get: Callable[[str], str]) -> None:
    """Discs page 1 under the exit rules: ten products and the next page,
    each at depth 1. The subcategory rule matches only facet links here, and
    every one of them is denied, so it keeps nothing."""
    found = run(get, DISCS, exit_rules())

    assert found.accepted["product_links"] == products(*range(1, 11))
    assert found.accepted["next_page"] == ((f"{BASE}{DISCS}?page=2", 1),)
    assert not found.accepted.get("subcategory_links")
    assert found.links() == [
        *found.accepted["product_links"],
        *found.accepted["next_page"],
    ]


def test_a_category_page_keeps_its_tiles_and_its_featured_product(
    get: Callable[[str], str],
) -> None:
    found = run(get, EXIT_SEED, exit_rules())

    assert found.accepted["subcategory_links"] == (
        (f"{BASE}/shop/cutting/discs/", 1),
        (f"{BASE}/shop/cutting/blades/", 1),
        (f"{BASE}{DEEP_PREFIX}1/", 1),
    )
    assert found.accepted["product_links"] == ((f"{BASE}/shop/p/HT-SB-001", 1),)
    assert not found.accepted.get("next_page"), "a category page has no pagination"


def test_a_faceted_listing_is_capped_by_deny_patterns_and_the_count_is_reported(
    get: Callable[[str], str],
) -> None:
    """Spec 004 §5: "a seed with a faceted listing is capped by
    `deny_patterns` and the dry-run reports the rejected count". One facet
    link per value on page 1, every one caught by the exit's single pattern."""
    found = run(get, DISCS, exit_rules())
    (pattern,) = exit_rules().deny_patterns

    assert denied(found) == {pattern: sum(len(v) for v in FACETS.values())}
    (tally,) = [r for r in found.rejected.values() if r.reason is RejectReason.DENY_PATTERN]
    assert tally.pattern == pattern
    assert tally.samples, "a reject reason with a count and no sample tells the operator nothing"
    assert len(tally.samples) < tally.count, "samples are a sample, not the whole list"
    facet_keys = set(FACETS)
    for sample in tally.samples:
        query = urlsplit(sample).query
        assert query and query.split("=", 1)[0] in facet_keys, sample


def test_every_partner_card_is_off_host_look_alikes_included(
    get: Callable[[str], str],
) -> None:
    """Spec 004 §5: discovery never leaves the domain. Two of the four
    cards end in `halden.test` and one starts with it; a suffix or prefix
    check keeps them."""
    found = run(get, DISCS, DiscoveryRules(product_links="a.product-card__link"))

    off = rejected(found, RejectReason.OFF_HOST)
    assert off is not None
    assert off.count == len(PARTNER_CARDS)
    assert set(off.samples) == set(PARTNER_CARDS)
    kept_hosts = {urlsplit(u).netloc for u, _ in found.links()}
    assert kept_hosts == {HOST}


@pytest.mark.parametrize("scheme", ["mailto", "tel", "javascript"])
def test_mailto_tel_and_javascript_are_rejected_as_scheme(
    get: Callable[[str], str], scheme: str
) -> None:
    found = run(get, ROOT, DiscoveryRules(subcategory_links="footer.site-footer a"))

    tally = rejected(found, RejectReason.SCHEME)
    assert tally is not None
    assert tally.count == 3
    assert any(s.lower().startswith(f"{scheme}:") for s in tally.samples), tally.samples
    assert not any(u.lower().startswith(f"{scheme}:") for u, _ in found.links())


def test_the_footers_off_host_links_are_rejected_off_host_not_scheme(
    get: Callable[[str], str],
) -> None:
    """The footer's other host and its subdomain: both `https`, so the only
    thing wrong with them is where they point."""
    found = run(get, ROOT, DiscoveryRules(subcategory_links="footer.site-footer a"))

    off = rejected(found, RejectReason.OFF_HOST)
    assert off is not None
    assert {urlsplit(s).netloc for s in off.samples} == {"elsewhere.test", f"cdn.{HOST}"}


def test_allow_patterns_keep_only_what_they_match(get: Callable[[str], str]) -> None:
    rules = DiscoveryRules(
        product_links="a.product-card__link",
        allow_patterns=(r"^/shop/p/HT-CD-00[1-5]$",),
    )
    found = run(get, DISCS, rules)

    assert found.accepted["product_links"] == products(1, 2, 3, 4, 5)
    not_allowed = rejected(found, RejectReason.NOT_ALLOWED)
    assert not_allowed is not None and not_allowed.count == 5
    assert set(paths(not_allowed.samples)) == {f"/shop/p/HT-CD-{n:03d}" for n in range(6, 11)}
    # Off-host is decided first: the partner cards are not "not allowed".
    off = rejected(found, RejectReason.OFF_HOST)
    assert off is not None and off.count == len(PARTNER_CARDS)


def test_patterns_are_searched_against_the_canonical_path_and_query(
    get: Callable[[str], str],
) -> None:
    """The page writes `/shop/cutting/discs/?page=2`; its canonical form has
    no trailing slash. A pattern written for the canonical form matches."""
    rules = DiscoveryRules(
        next_page="a[rel='next']", allow_patterns=(r"^/shop/cutting/discs\?page=2$",)
    )
    found = run(get, DISCS, rules)

    assert found.accepted["next_page"] == ((f"{BASE}{DISCS}?page=2", 1),)


def test_each_deny_pattern_is_counted_on_its_own(get: Callable[[str], str]) -> None:
    """Spec 004 §3: the report names the pattern that exploded. Two
    patterns tallied together could not."""
    rules = DiscoveryRules(
        subcategory_links="form.facets a", deny_patterns=(r"\?colour=", r"\?grit=")
    )
    found = run(get, DISCS, rules)

    assert denied(found) == {r"\?colour=": len(FACETS["colour"]), r"\?grit=": len(FACETS["grit"])}
    kept = {urlsplit(u).query.split("=", 1)[0] for u, _ in found.links()}
    assert kept == {"sort", "per_page"}


def test_the_domains_deny_patterns_apply_with_the_templates(
    get: Callable[[str], str],
) -> None:
    """Task "Decided": the template's `deny_patterns` ADD to the domain's.
    A link must pass both lists."""
    rules = DiscoveryRules(subcategory_links="form.facets a", deny_patterns=(r"\?colour=",))
    found = run(get, DISCS, rules, domain_deny=(r"\?sort=",))

    assert denied(found) == {r"\?colour=": len(FACETS["colour"]), r"\?sort=": len(FACETS["sort"])}
    kept = {urlsplit(u).query.split("=", 1)[0] for u, _ in found.links()}
    assert kept == {"grit", "per_page"}


def test_the_domains_deny_patterns_apply_when_the_template_has_none(
    get: Callable[[str], str],
) -> None:
    found = run(
        get, DISCS, DiscoveryRules(subcategory_links="form.facets a"), domain_deny=(r"\?grit=",)
    )

    assert denied(found) == {r"\?grit=": len(FACETS["grit"])}


# ---------------------------------------------------------------------------
# Depth (spec 004 §1 rule 5, §5)
# ---------------------------------------------------------------------------


def test_a_page_one_below_max_depth_yields_links_at_max_depth(
    get: Callable[[str], str],
) -> None:
    """`/shop/deep/4/` is depth 4 from the exit seed; its tile is
    `/shop/deep/5/`, which at `max_depth = 5` is enqueued."""
    found = run(get, f"{DEEP_PREFIX}4/", exit_rules(), depth=MAX_DEPTH - 1)

    assert found.links() == [(f"{BASE}{DEEP_PREFIX}5/", MAX_DEPTH)]
    assert rejected(found, RejectReason.DEPTH) is None


def test_a_page_at_max_depth_yields_no_links(get: Callable[[str], str]) -> None:
    """`/shop/deep/5/`'s tile would be depth 6. Rejected as `depth`, and
    counted, so the report says the cap was what stopped it."""
    found = run(get, f"{DEEP_PREFIX}5/", exit_rules(), depth=MAX_DEPTH)

    assert found.links() == []
    tally = rejected(found, RejectReason.DEPTH)
    assert tally is not None and tally.count == 1
    assert paths(tally.samples) == [f"{DEEP_PREFIX}6"]


def test_a_leaf_at_max_depth_keeps_none_of_its_products(get: Callable[[str], str]) -> None:
    """The same rule on a page with many links: every one that passed the
    other rules is a depth reject, none is accepted."""
    found = run(get, DISCS, exit_rules(), depth=MAX_DEPTH)

    assert found.links() == []
    tally = rejected(found, RejectReason.DEPTH)
    assert tally is not None and tally.count == 11  # ten products and the next page


# ---------------------------------------------------------------------------
# Hrefs that are not URLs, dedupe, spelling
# ---------------------------------------------------------------------------


def test_an_unparseable_href_is_counted_and_never_raised(get: Callable[[str], str]) -> None:
    broken = '<a href="http://[halden">a</a><a href="http://halden.test:99999/x">b</a>'
    footer = '<footer class="site-footer">'
    html = get(ROOT).replace(footer, footer + broken)
    assert "http://[halden" in html, "the footer's markup changed; the splice missed"

    found = run(get, ROOT, DiscoveryRules(subcategory_links="footer.site-footer a"), html=html)

    tally = rejected(found, RejectReason.UNPARSEABLE)
    assert tally is not None and tally.count == 2
    # The rest of the page is still discovered.
    scheme = rejected(found, RejectReason.SCHEME)
    assert scheme is not None and scheme.count == 3


def test_one_page_spelled_many_ways_is_one_link_in_the_first_spelling(
    get: Callable[[str], str],
) -> None:
    """The root's promo links discs under eleven spellings (tracking
    parameters, a fragment, `./..`, `//`, case, the default port, query
    order). They are three pages: the listing, `?colour&per_page`, and
    `?page=2`. Each comes out once, as the site first wrote it (the
    fetchable spelling: 2.2), not canonicalised."""
    found = run(get, ROOT, DiscoveryRules(subcategory_links="section.promo a"))

    assert found.accepted["subcategory_links"] == (
        (f"{BASE}{DISCS}?utm_source=newsletter&utm_medium=email", 1),
        (f"{BASE}{DISCS}?per_page=25&colour=red", 1),
        (f"{BASE}{DISCS}?page=2", 1),
    )


def test_an_accepted_link_never_carries_its_fragment(get: Callable[[str], str]) -> None:
    found = run(get, ROOT, DiscoveryRules(subcategory_links="section.promo a[href$='#top']"))

    assert found.links() == [(f"{BASE}{DISCS}", 1)]


def test_a_link_two_rules_match_belongs_to_the_product_rule(
    get: Callable[[str], str],
) -> None:
    """The featured product is matched by both rules here. It is a product
    link, recorded once, whatever order the selectors are written in."""
    rules = DiscoveryRules(
        subcategory_links="a.product-card__link, section.subcategories a",
        product_links="a.product-card__link",
    )
    found = run(get, EXIT_SEED, rules)

    assert found.accepted["product_links"] == ((f"{BASE}/shop/p/HT-SB-001", 1),)
    assert f"{BASE}/shop/p/HT-SB-001" not in [u for u, _ in found.accepted["subcategory_links"]]
    assert len(found.links()) == 4


def test_the_next_page_rule_outranks_the_subcategory_rule(get: Callable[[str], str]) -> None:
    """Page 2 is linked twice in discs' pagination, numbered and `rel=next`.
    A subcategory rule over the whole pagination block gets page 3 only."""
    rules = DiscoveryRules(next_page="a[rel='next']", subcategory_links="nav.pagination a")
    found = run(get, DISCS, rules)

    assert found.accepted["next_page"] == ((f"{BASE}{DISCS}?page=2", 1),)
    assert found.accepted["subcategory_links"] == ((f"{BASE}{DISCS}?page=3", 1),)


def test_dedupe_is_by_canonical_url_across_rules(get: Callable[[str], str]) -> None:
    """The tracking-parameter spelling is matched by the product rule; the
    subcategory rule's plain spellings of the same page are the same page."""
    rules = DiscoveryRules(
        product_links="section.promo a[href*='utm_source']",
        subcategory_links="section.promo a",
    )
    found = run(get, ROOT, rules)

    assert found.accepted["product_links"] == (
        (f"{BASE}{DISCS}?utm_source=newsletter&utm_medium=email", 1),
    )
    assert paths(u for u, _ in found.accepted["subcategory_links"]) == [
        "/shop/cutting/discs?per_page=25&colour=red",
        "/shop/cutting/discs?page=2",
    ]


def test_a_rejected_link_two_rules_match_is_counted_once(get: Callable[[str], str]) -> None:
    rules = DiscoveryRules(
        next_page="footer.site-footer a", subcategory_links="footer.site-footer a"
    )
    found = run(get, ROOT, rules)

    scheme = rejected(found, RejectReason.SCHEME)
    off = rejected(found, RejectReason.OFF_HOST)
    assert scheme is not None and scheme.count == 3
    assert off is not None and off.count == 2


def test_an_unset_rule_selects_nothing(get: Callable[[str], str]) -> None:
    found = run(get, DISCS, DiscoveryRules())

    assert found.links() == []
    assert not found.rejected


# ---------------------------------------------------------------------------
# Pure
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


def test_discover_imports_nothing_that_could_write() -> None:
    """The dry-run (2.10) shares this function, and a dry-run that wrote
    would not be one. Checked on the module's imports, as
    `test_import_contracts.py` checks `domain/`."""
    source = Path(inspect.getfile(links_module)).read_text()
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offending = [m for m in imported if any(m == p or m.startswith(p + ".") for p in _IO_MODULES)]
    assert offending == []
    assert not inspect.iscoroutinefunction(discover)


def test_discover_requests_nothing_and_gives_the_same_answer_twice(
    get: Callable[[str], str], site: FixtureSite
) -> None:
    html = get(DISCS)
    before = len(site.requests)

    first = run(get, DISCS, exit_rules(), html=html)
    second = run(get, DISCS, exit_rules(), html=html)

    assert len(site.requests) == before, "discover fetched something"
    assert first == second
