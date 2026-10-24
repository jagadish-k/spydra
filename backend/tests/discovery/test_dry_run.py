"""`dry_run()`: the one-page preview of what a crawl would enqueue (spec 004
§4, §3a; BUILD_PLAN 2.10).

Behaviour is asserted against Halden served over loopback — the real fixture
site through the real static fetcher for everything the site can produce
(counts, findings, projections, the two-request posture), and a scripted
fetcher rendering the same catalogue for the outcomes it cannot (a
disallowing or failing `robots.txt`, a page that never answers, backpressure,
a listing whose links exist only after JS).

The projection is never asserted as a number: every expected value is the
pinned formula computed from the report's own matched counts, the way spec
004 §4 states it. The three §3a comparison cases (redundant rule, load-bearing
rule, scoped-over-the-same-page) are the amended check demonstrated both
ways.

Writes-nothing is proven three ways, per the contract: an AST allowlist over
the module's imports (2.9's pattern, with the relative-import hole closed and
the one sanctioned `scheduler.robots` import on the list — and that module
pinned in turn to stdlib + domain + ports, so the purity is transitive), the
request counts under every outcome, and a real engine counting every table
the `crawl` schema owns before and after.
"""

import ast
import inspect
from collections.abc import Callable, Iterator
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.discovery import dry_run as dry_run_module
from spydra.discovery.dry_run import (
    FETCH_FAILED,
    NON_200,
    ROBOTS_DISALLOWED,
    ROBOTS_UNAVAILABLE,
    ZERO_LINKS_STATIC,
    DryRunReport,
    RuleMatch,
    dry_run,
)
from spydra.discovery.links import _SAMPLES
from spydra.domain.entities import DiscoveryRules
from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.domain.urls import canonical_url
from spydra.scheduler import robots as robots_module
from tests.adapters.postgres.seed import seed_domain
from tests.fixtures import catalogue
from tests.fixtures.catalogue import (
    EXIT_DISCOVERY,
    EXIT_SEED,
    FACETS,
    HOST,
    NODES,
    PARTNER_CARDS,
    PER_PAGE,
    TREE,
)
from tests.fixtures.server import FixtureSite

# Halden's pages by role. A category page carries the mega-menu and no
# pagination, so `nav a` there matches exactly the mega links (2.6's note).
CUTTING = TREE[0].path
DISCS = TREE[0].children[0].path
BLADES = TREE[0].children[1].path
SCOPED = "section.subcategories a"
MAX_DEPTH = 5
UA = "SpydraTest/1.0 (+https://spydra.test)"

# The catalogue's own numbers, derived once: the leaf spans three pages of
# PER_PAGE, page 1 carries every facet value as a link, and the category page
# carries its children's tiles plus the archive tile.
DISCS_PAGES = -(-TREE[0].children[0].products // PER_PAGE)
FACET_LINKS = sum(len(values) for values in FACETS.values())
CUTTING_TILES = len(TREE[0].children) + 1  # + the archive tile (catalogue._listing)
EXIT_PATTERN = str(cast(list[str], EXIT_DISCOVERY["deny_patterns"])[0])

# The mega-menu finding's numbers, derived exactly as test_mega_menu derives
# them: every node linked once, the top categories the spanning roots, the
# deepest ancestor chain the level count.
BASE = f"http://{HOST}"
MEGA_LINKS = len(NODES)
LEVELS = 1 + max(
    sum(node.path != other.path and node.path.startswith(other.path) for other in NODES)
    for node in NODES
)


def _canon(site_path: str) -> str:
    return urlsplit(canonical_url(f"{BASE}{site_path}")).path


BRANCH_SAMPLE = tuple(sorted(_canon(node.path) for node in TREE))


def exit_rules() -> DiscoveryRules:
    """`EXIT_DISCOVERY` as the template codec would read it (2.3's helper)."""
    raw = EXIT_DISCOVERY
    return DiscoveryRules(
        product_links=str(raw["product_links"]),
        next_page=str(raw["next_page"]),
        subcategory_links=str(raw["subcategory_links"]),
        deny_patterns=tuple(cast(list[str], raw["deny_patterns"])),
    )


def rule_count(report: DryRunReport, rule: str) -> int:
    match = report.matched.get(rule)
    return match.count if match is not None else 0


def expected_projection(products: int, next_pages: int, subcategories: int, max_depth: int) -> int:
    """Spec 004 §4's formula, transcribed: `t = p + n + s`, `f = n + s`,
    geometric when `f > 1`, linear when `f = 1`, the page total when `f = 0`.

    An independent transcription, not a call into the module: if the
    implementation drifts from the spec's arithmetic, this disagrees."""
    t = products + next_pages + subcategories
    f = next_pages + subcategories
    if f > 1:
        # `int()` because typeshed's `int.__pow__` is declared `-> Any` —
        # the same non-reason dry_run.py's own comment gives.
        return int(t * (f**max_depth - 1) // (f - 1))
    if f == 1:
        return t * max_depth
    return t


def report_projection(report: DryRunReport) -> int:
    """The formula over a report's own matched counts — what its projection
    must equal, whatever the page."""
    return expected_projection(
        rule_count(report, "product_links"),
        rule_count(report, "next_page"),
        rule_count(report, "subcategory_links"),
        MAX_DEPTH,
    )


@pytest.fixture(scope="module")
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as s:
        yield s


async def dry(
    site: FixtureSite, path: str, rules: DiscoveryRules, *, max_depth: int = MAX_DEPTH
) -> DryRunReport:
    """A dry-run through the real static fetcher, as a STATIC domain's caller
    composes it: one fetcher for robots and for the page."""
    static = HttpxFetcher(SystemClock())
    try:
        return await dry_run(
            site.base_url + path,
            rules,
            static=static,
            page=static,
            host=urlsplit(site.base_url).netloc,
            user_agent=UA,
            max_depth=max_depth,
        )
    finally:
        await static.aclose()


# ---------------------------------------------------------------------------
# A scripted fetcher: the outcomes the fixture site cannot serve
# ---------------------------------------------------------------------------

Response = tuple[int, str] | Exception

# The two robots bodies the fixture site cannot serve for a scripted page
# host: the permissive text it answers every unknown host with, and
# disallow-all.txt's.
PERMISSIVE = "User-agent: *\nAllow: /"
DISALLOW_ALL = "User-agent: *\nDisallow: /"

# A JS-dependent listing's server HTML: the product grid exists only after
# the script runs, so a parser sees zero links however good the rule is.
# STUB_ONLY's shape (test_page_crawler), with the link visible in the source
# to prove it is the DOM, not the bytes, that is missing it.
JS_ONLY_LISTING = """<!doctype html>
<title>discs</title>
<ul id="grid"></ul>
<script>
  document.getElementById("grid").innerHTML =
    '<a class="product-card__link" href="/shop/p/HT-CD-001">Disc</a>';
</script>
"""


def halden(request: FetchRequest) -> Response:
    """The fixture catalogue's answer, rendered not fetched — the recorded
    site, for tests that script the robots answer around it."""
    parts = urlsplit(request.url)
    rendered = catalogue.render(parts.path, parts.query, HOST)
    if rendered is None:
        return 404, "<!doctype html><title>404</title>"
    return rendered[0], rendered[1].decode()


def _page(request: FetchRequest, status: int, body: str, path: FetchPath) -> FetchedPage:
    return FetchedPage(
        request_url=request.url,
        final_url=request.url,
        http_status=status,
        body=body,
        headers={},
        fetched_at=datetime.now(UTC),
        elapsed_ms=5,
        fetch_path=path,
    )


class Answering:
    """A `Fetcher` whose robots answer and page answer the test scripts, with
    every fetch counted by kind — `robots_calls` and `page_calls` are the
    posture assertions' evidence."""

    def __init__(
        self,
        *,
        robots: tuple[int, str] | Exception = (200, PERMISSIVE),
        answer: Callable[[FetchRequest], Response] = halden,
        path: FetchPath = FetchPath.STATIC,
    ) -> None:
        self.path = path
        self._robots = robots
        self._answer = answer
        self.robots_calls = 0
        self.page_calls = 0

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        if request.url.endswith("/robots.txt"):
            self.robots_calls += 1
            if isinstance(self._robots, Exception):
                raise self._robots
            return _page(request, *self._robots, self.path)
        self.page_calls += 1
        result = self._answer(request)
        if isinstance(result, Exception):
            raise result
        status, body = result
        return _page(request, status, body, self.path)

    async def aclose(self) -> None:
        pass


async def scripted(
    rules: DiscoveryRules,
    path: str,
    *,
    static: Answering | None = None,
    page: Answering | None = None,
    max_depth: int = MAX_DEPTH,
) -> tuple[DryRunReport, Answering, Answering]:
    """A dry-run over `halden.test` with scripted fetchers; returns the
    report and both fetchers for their call counts."""
    static = static if static is not None else Answering()
    page = page if page is not None else static
    report = await dry_run(
        BASE + path,
        rules,
        static=static,
        page=page,
        host=HOST,
        user_agent=UA,
        max_depth=max_depth,
    )
    return report, static, page


# ---------------------------------------------------------------------------
# Counts per rule, against the catalogue's constants (spec 004 §4, §5)
# ---------------------------------------------------------------------------


async def test_a_leaf_listing_reports_the_catalogues_counts_per_rule(site: FixtureSite) -> None:
    """Discs page 1 under the exit rules: `PER_PAGE` products (page 1 of the
    leaf's set), one next page (the leaf spans more than one page), and a
    subcategory rule that kept nothing — every facet link it matched was
    denied. A page that fetched, parsed and matched carries no notice."""
    report = await dry(site, DISCS, exit_rules())

    assert report.http_status == 200
    assert report.notices == ()
    assert report.final_url == site.base_url + DISCS
    assert report.fetch_path is FetchPath.STATIC
    assert rule_count(report, "product_links") == PER_PAGE
    assert rule_count(report, "next_page") == int(DISCS_PAGES > 1)
    assert "subcategory_links" not in report.matched


async def test_a_category_page_reports_its_tiles_and_its_featured_product(
    site: FixtureSite,
) -> None:
    report = await dry(site, EXIT_SEED, exit_rules())

    assert rule_count(report, "subcategory_links") == CUTTING_TILES
    assert rule_count(report, "product_links") == 1  # the featured product
    assert rule_count(report, "next_page") == 0
    assert report.rejected == {}, "nothing on a category page is a reject under these rules"


async def test_facet_rejects_surface_unchanged_pattern_count_and_sample(
    site: FixtureSite,
) -> None:
    """Spec 004 §5's second half: the dry-run reports the rejected count.
    The tally is `discover`'s verbatim — a deny-keyed entry carrying the
    pattern, the count and a sample — and the partner cards are the off-host
    half of the same page."""
    report = await dry(site, DISCS, exit_rules())

    assert set(report.rejected) == {f"deny_pattern:{EXIT_PATTERN}", "off_host"}
    deny = report.rejected[f"deny_pattern:{EXIT_PATTERN}"]
    assert deny.count == FACET_LINKS
    assert deny.pattern == EXIT_PATTERN
    assert deny.samples, "a count with no sample tells the operator nothing"
    assert len(deny.samples) < deny.count, "samples are a sample, not the list"
    facet_keys = set(FACETS)
    for sample in deny.samples:
        query = urlsplit(sample).query
        assert query and query.split("=", 1)[0] in facet_keys, sample
    assert report.rejected["off_host"].count == len(PARTNER_CARDS)


async def test_samples_are_absolute_fetchable_urls_capped_at_the_shared_limit(
    site: FixtureSite,
) -> None:
    """The first `_SAMPLES` accepted links, as absolute spellings an operator
    can open — derived from the catalogue's own order, not copied."""
    report = await dry(site, DISCS, exit_rules())
    discs = TREE[0].children[0]

    products = report.matched["product_links"]
    assert products.sample == tuple(
        f"{site.base_url}/shop/p/{sku}" for sku in discs.skus[:_SAMPLES]
    )
    assert len(products.sample) == min(products.count, _SAMPLES)
    for url in products.sample:
        assert url.startswith(site.base_url) and "#" not in url


async def test_the_report_carries_exactly_spec_004_section_4s_keys(
    site: FixtureSite,
) -> None:
    """The spec's example keys are the report's fields, exactly: the review
    screen (3.14) builds against this shape, so a field nobody spec'd cannot
    appear and a spec'd one cannot go missing."""
    assert [f.name for f in fields(DryRunReport)] == [
        "matched",
        "rejected",
        "mega_menu",
        "projected_urls_at_max_depth",
        "fetch_path",
        "http_status",
        "final_url",
        "notices",
    ]
    assert [f.name for f in fields(RuleMatch)] == ["count", "sample"]

    report = await dry(site, DISCS, exit_rules())
    assert f"deny_pattern:{EXIT_PATTERN}" in report.rejected, report.rejected.keys()


# ---------------------------------------------------------------------------
# The projection: three branches, the formula, and §3a's comparison
# ---------------------------------------------------------------------------


async def test_a_fan_out_above_one_projects_geometrically(site: FixtureSite) -> None:
    """The exit seed: one featured product and three tiles — `f = 3` expands,
    so the geometric sum applies. `t · (f^D − 1)/(f − 1)`, derived, not
    asserted as 484."""
    report = await dry(site, EXIT_SEED, exit_rules())
    products, next_pages, subcategories = (
        rule_count(report, "product_links"),
        rule_count(report, "next_page"),
        rule_count(report, "subcategory_links"),
    )

    assert (products, next_pages, subcategories) == (1, 0, CUTTING_TILES)
    assert next_pages + subcategories > 1, "the branch's precondition drifted"
    assert report.projected_urls_at_max_depth == report_projection(report)


@pytest.mark.parametrize("depth", [5, 3])
async def test_a_unit_fan_out_projects_linearly(site: FixtureSite, depth: int) -> None:
    """The leaf: `PER_PAGE` products and one next page — `f = 1`, every page
    replaces itself, so the projection is `t · max_depth`. Parametrised over
    the depth so the key's "at max_depth", not "at 5", is what is tested."""
    report = await dry(site, DISCS, exit_rules(), max_depth=depth)
    products, next_pages, subcategories = (
        rule_count(report, "product_links"),
        rule_count(report, "next_page"),
        rule_count(report, "subcategory_links"),
    )

    assert (products, next_pages, subcategories) == (PER_PAGE, 1, 0)
    assert report.projected_urls_at_max_depth == (PER_PAGE + 1) * depth


async def test_a_leaf_fan_out_of_zero_projects_the_page_total(site: FixtureSite) -> None:
    """Blades: every product on one page, no pagination, every facet link
    denied — `f = 0`, nothing expands, so the projection is `t` itself."""
    blades = TREE[0].children[1]

    report = await dry(site, BLADES, exit_rules())

    assert set(report.matched) == {"product_links"}
    assert rule_count(report, "product_links") == blades.products
    assert report.projected_urls_at_max_depth == blades.products


async def test_same_inputs_give_the_same_number() -> None:
    """Deterministic by construction: two calls over the same page agree —
    and the per-call robots cache means two calls are two robots fetches."""
    first, static_one, _ = await scripted(exit_rules(), DISCS)
    second, static_two, _ = await scripted(exit_rules(), DISCS, static=static_one)

    assert first.projected_urls_at_max_depth == second.projected_urls_at_max_depth
    assert first.matched == second.matched
    assert static_one.robots_calls == 2, "the cache outlived its call"


# ---------------------------------------------------------------------------
# The mega-menu finding reaches the report (spec 004 §5, §3a)
# ---------------------------------------------------------------------------


async def test_a_nav_rule_reports_the_whole_tree_finding_and_the_hazard_projection(
    site: FixtureSite,
) -> None:
    """2.6's flag in the report it was shaped for: `nav a` on the category
    page — 11 links, 3 branches, deepest chain 3, all derived from the
    catalogue — and `t = f = 11, D = 5` projects 11·(11⁵−1)/10 = 177,155:
    the hazard signal, derived from the matched counts by the pinned
    formula."""
    report = await dry(site, CUTTING, DiscoveryRules(subcategory_links="nav a"))

    finding = report.mega_menu
    assert finding is not None
    assert finding.links == finding.paths == MEGA_LINKS
    assert finding.branches == len(TREE)
    assert finding.levels == LEVELS
    assert finding.roots == BRANCH_SAMPLE
    assert (rule_count(report, "product_links"), rule_count(report, "next_page")) == (0, 0)
    assert rule_count(report, "subcategory_links") == MEGA_LINKS
    assert report.projected_urls_at_max_depth == report_projection(report)
    assert report.matched["subcategory_links"].sample == tuple(
        f"{site.base_url}{node.path}" for node in NODES[:_SAMPLES]
    )


async def test_a_scoped_rule_over_the_same_page_carries_no_finding(
    site: FixtureSite,
) -> None:
    """The same page under the scoped rule: no finding, and the projection
    two orders of magnitude below the `nav a` one — the gap is the whole
    point of the report."""
    scoped = await dry(site, CUTTING, DiscoveryRules(subcategory_links=SCOPED))
    nav = await dry(site, CUTTING, DiscoveryRules(subcategory_links="nav a"))

    assert scoped.mega_menu is None
    assert rule_count(scoped, "subcategory_links") == CUTTING_TILES
    assert scoped.projected_urls_at_max_depth < nav.projected_urls_at_max_depth


# ---------------------------------------------------------------------------
# §3a's comparison, both ways (spec 004 §3a as amended)
# ---------------------------------------------------------------------------


async def test_removing_a_rule_that_only_reattributes_leaves_the_projection_unchanged(
    site: FixtureSite,
) -> None:
    """`nav.mega a` as the product rule takes all eleven links by
    first-match attribution, so the `nav a` subcategory rule enqueues
    nothing the product rule does not: with it or without it, `t` is 11 and
    the projection is identical. The amended check's verdict: delete it."""
    both = await dry(
        site, CUTTING, DiscoveryRules(product_links="nav.mega a", subcategory_links="nav a")
    )
    alone = await dry(site, CUTTING, DiscoveryRules(product_links="nav.mega a"))

    assert rule_count(both, "product_links") == rule_count(alone, "product_links") == MEGA_LINKS
    assert rule_count(both, "subcategory_links") == 0
    assert both.projected_urls_at_max_depth == alone.projected_urls_at_max_depth


async def test_removing_a_load_bearing_rule_lowers_the_projection(
    site: FixtureSite,
) -> None:
    """The exit rules minus the subcategory rule on the same seed: the tiles
    were the fan-out, and the projection collapses. Whether what was lost is
    coverage or shortcut is the operator's call — the report's job is to say
    that volume moved."""
    full = await dry(site, EXIT_SEED, exit_rules())
    pruned = await dry(
        site,
        EXIT_SEED,
        DiscoveryRules(
            product_links=str(EXIT_DISCOVERY["product_links"]),
            next_page=str(EXIT_DISCOVERY["next_page"]),
        ),
    )

    assert pruned.projected_urls_at_max_depth < full.projected_urls_at_max_depth


# ---------------------------------------------------------------------------
# Writes nothing, way one: the module's imports (2.9's pattern)
# ---------------------------------------------------------------------------

# The contract's allowlist: stdlib, the pure discovery members, domain, the
# one port — and `spydra.scheduler.robots`, the one scheduler import the
# contract mandates (RobotsCache reused verbatim; itself pinned by the next
# test). An allowlist, not a denylist: a module nobody has imagined yet is
# refused by default.
_ALLOWED_IMPORTS = (
    "collections.abc",
    "dataclasses",
    "urllib.parse",
    "spydra.discovery.links",
    "spydra.discovery.mega_menu",
    "spydra.domain.entities",
    "spydra.domain.enums",
    "spydra.domain.errors",
    "spydra.domain.fetch",
    "spydra.ports.fetcher",
    "spydra.scheduler.robots",
)

_ROBOTS_ALLOWED_IMPORTS = (
    "logging",
    "dataclasses",
    "urllib.parse",
    "urllib.robotparser",
    "spydra.domain.errors",
    "spydra.domain.fetch",
    "spydra.ports.fetcher",
)


def _imports_of(module: object) -> list[str]:
    """Every module `module` imports, relative imports recorded rather than
    skipped (2.9's fix: `from . import x` must be visible to the allowlist)."""
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")  # type: ignore[arg-type]
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported.append("." * node.level + (node.module or ""))
            else:
                assert node.module is not None  # a level-0 import always names one
                imported.append(node.module)
    assert imported, "the walk read no imports; the test proves nothing"
    return imported


def _offending(imported: list[str], allowed: tuple[str, ...]) -> list[str]:
    return [
        module
        for module in imported
        if not any(module == allowed or module.startswith(allowed + ".") for allowed in allowed)
    ]


def test_the_dry_run_imports_only_what_the_contract_allows() -> None:
    """No engine, no adapter, no repository — nothing that could write. The
    one scheduler import is `scheduler.robots`, named in the contract."""
    assert _offending(_imports_of(dry_run_module), _ALLOWED_IMPORTS) == []


def test_the_reused_robots_module_imports_only_domain_ports_and_stdlib() -> None:
    """The allowlist's one non-discovery entry earns its place: the module
    the dry-run reaches outside `discovery/` for is itself pure over domain,
    ports and the standard library, so the purity is transitive."""
    assert _offending(_imports_of(robots_module), _ROBOTS_ALLOWED_IMPORTS) == []


# ---------------------------------------------------------------------------
# Writes nothing, way two: one robots request, at most one page request,
# under every outcome
# ---------------------------------------------------------------------------


async def test_one_dry_run_is_one_robots_request_then_one_page_request() -> None:
    """The posture, against the real site: the fixture server sees exactly
    the robots fetch and the page fetch, in that order — the check precedes
    the fetch it guards."""
    with FixtureSite() as fixture:
        static = HttpxFetcher(SystemClock())
        try:
            report = await dry_run(
                fixture.base_url + DISCS,
                exit_rules(),
                static=static,
                page=static,
                host=urlsplit(fixture.base_url).netloc,
                user_agent=UA,
            )
        finally:
            await static.aclose()

    assert report.http_status == 200 and report.matched
    assert fixture.requests == [("127.0.0.1", "/robots.txt"), ("127.0.0.1", DISCS)]


async def test_without_respect_for_robots_there_is_no_robots_request() -> None:
    """The operator override: the page is fetched, `robots.txt` never asked
    for — zero robots requests, one page request."""
    with FixtureSite() as fixture:
        static = HttpxFetcher(SystemClock())
        try:
            report = await dry_run(
                fixture.base_url + DISCS,
                exit_rules(),
                static=static,
                page=static,
                host=urlsplit(fixture.base_url).netloc,
                user_agent=UA,
                respect_robots=False,
            )
        finally:
            await static.aclose()

    assert report.http_status == 200 and report.matched
    assert fixture.requests == [("127.0.0.1", DISCS)]


async def test_a_disallowing_robots_txt_reports_and_fetches_nothing() -> None:
    """The crawl would refuse the domain, so the preview does too: the
    notice, zero page requests, and the empty report that still names the
    posture the operator configured (`page.path`, here RENDERED to pin that
    it is the caller's fetcher, not a default)."""
    static = Answering(robots=(200, DISALLOW_ALL))
    page = Answering(path=FetchPath.RENDERED)

    report, robots_fetcher, page_fetcher = await scripted(
        exit_rules(), DISCS, static=static, page=page
    )

    assert report.notices == (ROBOTS_DISALLOWED,)
    assert robots_fetcher.robots_calls == 1
    assert page_fetcher.page_calls == 0
    assert report.http_status is None
    assert report.final_url == ""
    assert report.fetch_path is FetchPath.RENDERED
    assert not report.matched and not report.rejected
    assert report.mega_menu is None and report.projected_urls_at_max_depth == 0


@pytest.mark.parametrize(
    "robots",
    [
        pytest.param((503, "unavailable"), id="5xx"),
        pytest.param(FetchFailed("robots timed out"), id="fetch-failed"),
    ],
)
async def test_a_robots_that_cannot_answer_fails_closed_with_zero_page_requests(
    robots: tuple[int, str] | FetchFailed,
) -> None:
    """Spec 002 §5's fail-closed, reported rather than silently zero: a 5xx
    or a robots fetch that never answered stops the dry-run before the page."""
    static = Answering(robots=robots)

    report, robots_fetcher, page_fetcher = await scripted(exit_rules(), DISCS, static=static)

    assert report.notices == (ROBOTS_UNAVAILABLE,)
    assert robots_fetcher.robots_calls == 1
    assert page_fetcher.page_calls == 0
    assert report.http_status is None and report.final_url == ""


# ---------------------------------------------------------------------------
# Failure edges
# ---------------------------------------------------------------------------


async def test_a_non_200_page_reports_the_status_and_runs_no_discovery() -> None:
    """Rules run against a 403 body are garbage, so a non-200 means no
    `discover` at all: the status is carried, everything matched is empty —
    and the whole call was still exactly the two requests."""
    with FixtureSite() as fixture:
        static = HttpxFetcher(SystemClock())
        missing = fixture.base_url + "/shop/nope/"
        try:
            report = await dry_run(
                missing,
                exit_rules(),
                static=static,
                page=static,
                host=urlsplit(fixture.base_url).netloc,
                user_agent=UA,
            )
        finally:
            await static.aclose()

    assert report.notices == (NON_200,)
    assert report.http_status == 404
    assert report.final_url == missing
    assert not report.matched and not report.rejected
    assert report.projected_urls_at_max_depth == 0 and report.mega_menu is None
    assert fixture.requests == [("127.0.0.1", "/robots.txt"), ("127.0.0.1", "/shop/nope/")]


async def test_a_page_that_never_answered_reports_fetch_failed() -> None:
    static = Answering(answer=lambda request: FetchFailed("connection refused"))

    report, _, _ = await scripted(exit_rules(), DISCS, static=static)

    assert report.notices == (FETCH_FAILED,)
    assert report.http_status is None and report.final_url == ""
    assert report.fetch_path is FetchPath.STATIC
    assert not report.matched


async def test_backpressure_from_the_page_fetcher_propagates() -> None:
    """The port contract: a busy sidecar is not a fetch failure and not the
    supplier's doing, and a dry-run has no row to requeue — the caller
    retries, so nothing is swallowed into a notice."""
    static = Answering()

    with pytest.raises(Backpressure):
        await scripted(
            exit_rules(),
            DISCS,
            page=Answering(answer=lambda request: Backpressure("sidecar busy")),
            static=static,
        )


# ---------------------------------------------------------------------------
# The loud zero: AUTO ≡ static (ADR-0039, by way of the caller's fetcher)
# ---------------------------------------------------------------------------


async def test_a_static_fetch_that_finds_no_links_is_reported_loudly() -> None:
    """The AUTO-drift signal: an AUTO listing resolves to a static-first
    fetch, and the crawl on AUTO would discover nothing from a JS-dependent
    listing — so the preview reports zero WITH the notice, never silently
    (rendering it would approve rules the crawl applies differently)."""
    report, _, page = await scripted(
        exit_rules(), DISCS, page=Answering(answer=lambda request: (200, JS_ONLY_LISTING))
    )

    assert page.path is FetchPath.STATIC
    assert report.http_status == 200
    assert not report.matched and not report.rejected
    assert report.notices == (ZERO_LINKS_STATIC,)
    assert report.projected_urls_at_max_depth == 0


async def test_a_rendered_fetch_that_finds_no_links_carries_no_notice() -> None:
    """Zero links in fully rendered HTML is an unambiguous broken selector,
    not the AUTO ambiguity — a rendered fetch stays silent."""
    report, _, page = await scripted(
        exit_rules(),
        DISCS,
        static=Answering(),
        page=Answering(path=FetchPath.RENDERED, answer=lambda request: (200, JS_ONLY_LISTING)),
    )

    assert page.path is FetchPath.RENDERED
    assert report.http_status == 200
    assert not report.matched
    assert report.notices == ()


# ---------------------------------------------------------------------------
# Writes nothing, way three: a real engine sees zero rows
# ---------------------------------------------------------------------------


async def crawl_table_counts(engine: AsyncEngine) -> dict[str, int]:
    """Row counts for every table the crawl schema owns — every table, not
    a list hand-copied here, so a future table joins the guarantee for
    free."""
    async with engine.connect() as conn:
        names = (
            (
                await conn.execute(
                    sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'crawl'")
                )
            )
            .scalars()
            .all()
        )
        assert names, "the crawl schema has no tables; the engine is not real"
        return {
            name: (
                await conn.execute(sa.text(f'SELECT count(*) FROM "crawl"."{name}"'))
            ).scalar_one()
            for name in names
        }


@pytest.mark.integration
async def test_a_dry_run_writes_no_rows_in_any_table_the_crawl_schema_owns(
    clean_crawl: AsyncEngine,
) -> None:
    """The construction claim, checked from outside: a live crawl schema
    with a domain row in it is byte-for-byte unchanged after a dry-run that
    demonstrably ran."""
    engine = clean_crawl
    await seed_domain(engine, "halden.test")
    with FixtureSite() as fixture:
        static = HttpxFetcher(SystemClock())
        try:
            before = await crawl_table_counts(engine)
            report = await dry_run(
                fixture.base_url + DISCS,
                exit_rules(),
                static=static,
                page=static,
                host=urlsplit(fixture.base_url).netloc,
                user_agent=UA,
            )
        finally:
            await static.aclose()

    assert report.http_status == 200 and report.matched, "the dry-run did not run"
    assert await crawl_table_counts(engine) == before
