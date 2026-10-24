"""What a crawl from this one page would enqueue (spec 004 §4; BUILD_PLAN 2.10).

**`discovery/`'s one impure member.** `canonical.py`, `links.py` and
`mega_menu.py` are pure; this module talks to the `Fetcher` port — never an
adapter — and to nothing else. No engine, connection, repository or frontier
appears anywhere in its signature, so it cannot write anything by
construction: the seeds screen (3.13) and the review screen (3.14) reach it
through an API route later, and today's callers are tests.

Everything shareable is shared (ADR-0019, by analogy — a second discovery
implementation is the defect that ADR names): `discover` is the engine the
crawl runs, `whole_tree` is 2.6's finding, `Rejected` is the tally shape,
`_SAMPLES` is the sample cap, `RobotsCache` is robots. New code here is one
report dataclass and the orchestration around one fetch.

The caller resolves `page` per the domain's `render_mode` through
`Fetchers.for_mode` — the same composition point the worker uses — so the
dry-run never learns about render modes. AUTO resolves to `AutoFetcher`,
whose fetch is static-first, and **an AUTO listing gets no rendered second
chance here** (ADR-0039): the dry-run previews the crawl, and the crawl on
AUTO discovers nothing from a JS-dependent listing. A static fetch that
accepts zero links is therefore reported loudly (`zero_links_static`)
rather than rendered around — rendering it would approve rules the crawl
applies differently.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from spydra.discovery.links import _SAMPLES, RULES, Rejected, discover
from spydra.discovery.mega_menu import MegaMenuFinding, whole_tree
from spydra.domain.entities import DiscoveryRules
from spydra.domain.enums import FetchPath
from spydra.domain.errors import FetchFailed
from spydra.domain.fetch import FetchRequest
from spydra.ports.fetcher import Fetcher
from spydra.scheduler.robots import RobotsCache

# Robots notice tokens, and the report's other edges, as one vocabulary:
# 3.13/3.14 map these to operator copy, so they are the API until then.
ROBOTS_DISALLOWED = "robots_disallowed"
ROBOTS_UNAVAILABLE = "robots_unavailable"
FETCH_FAILED = "fetch_failed"
NON_200 = "non_200"
ZERO_LINKS_STATIC = "zero_links_static"


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One rule's kept links: how many, and the first `_SAMPLES` as
    absolute fetchable spellings — an operator must be able to open one."""

    count: int
    sample: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """The one-page preview a review screen renders (spec 004 §4).

    `matched` is keyed by rule name with the count and a sample;
    `rejected` is `discover`'s tally verbatim, keyed `off_host` /
    `deny_pattern:<pattern>`; `mega_menu` is 2.6's whole-tree finding when
    the subcategory rule spans the site, else `None`;
    `projected_urls_at_max_depth` is the fan-out estimate — an estimate,
    not a count of known URLs: it cannot see dedupe or the site's closure
    (spec 004 §4's semantics paragraph).

    `fetch_path` is the path the crawl would use when nothing was fetched,
    else the path that actually served the page (an AUTO fallback shows up
    here as RENDERED). `http_status` is `None` when no response came back,
    and `final_url` is `""` then — there is no final URL to name. `notices`
    are the tokens above; empty means the page fetched, parsed and matched.
    """

    matched: Mapping[str, RuleMatch]
    rejected: Mapping[str, Rejected]
    mega_menu: MegaMenuFinding | None
    projected_urls_at_max_depth: int
    fetch_path: FetchPath
    http_status: int | None
    final_url: str
    notices: tuple[str, ...]


async def dry_run(
    page_url: str,
    rules: DiscoveryRules,
    *,
    static: Fetcher,
    page: Fetcher,
    host: str,
    user_agent: str,
    max_depth: int = 5,
    domain_deny: Sequence[str] = (),
    respect_robots: bool = True,
) -> DryRunReport:
    """Fetch one listing page and report what a crawl from it would enqueue.

    One robots request (through `static` — rendering a text file through
    Playwright would be absurd) and at most one page request (through
    `page`, already resolved per the domain's `render_mode` by the caller).
    A robots disallow or a fail-closed robots fetch makes **zero** page
    requests: the crawl being previewed would refuse the domain, so
    the report says so instead of silently reporting zero links.

    `Backpressure` propagates: a busy sidecar of ours is not a fetch
    failure (ports/fetcher.py) and not a fact about the supplier, so it is
    the caller's to retry rather than this report's to explain.
    """
    # `run_id` is cache identity only (scheduler/robots.py), and this cache
    # dies with the call: one robots fetch per dry-run, whatever the caller
    # does next.
    robots = await RobotsCache(static).rules_for(
        0,
        host,
        user_agent,
        respect_robots=respect_robots,
        scheme=urlsplit(page_url).scheme or "https",
    )
    if not robots.allowed_at_all:
        return _nothing(page, ROBOTS_UNAVAILABLE)
    if not robots.can_fetch(page_url):
        return _nothing(page, ROBOTS_DISALLOWED)

    try:
        fetched = await page.fetch(FetchRequest(url=page_url, user_agent=user_agent))
    except FetchFailed:
        return _nothing(page, FETCH_FAILED)

    if fetched.http_status != 200:
        # Rules run against a 403 body are garbage; the status and the
        # served URL still tell the operator what happened.
        return DryRunReport(
            matched={},
            rejected={},
            mega_menu=None,
            projected_urls_at_max_depth=0,
            fetch_path=fetched.fetch_path,
            http_status=fetched.http_status,
            final_url=fetched.final_url,
            notices=(NON_200,),
        )

    # The page is a seed: depth 0, links at 1, discovered from the URL the
    # body was served from (links.py's contract for relative hrefs).
    discovery = discover(
        fetched.body,
        fetched.final_url,
        rules,
        host=host,
        depth=0,
        max_depth=max_depth,
        domain_deny=domain_deny,
    )
    # The finding reads the full discovery — before any sample view exists,
    # so capping samples can never shrink it.
    finding = whole_tree(discovery)

    matched: dict[str, RuleMatch] = {}
    counts: dict[str, int] = {}
    for rule in RULES:
        links = discovery.accepted.get(rule, ())
        if not links:
            continue
        matched[rule] = RuleMatch(
            count=len(links),
            sample=tuple(url for url, _ in links[:_SAMPLES]),
        )
        counts[rule] = len(links)

    notices: tuple[str, ...] = ()
    if fetched.fetch_path is FetchPath.STATIC and not discovery.links():
        # The ambiguous zero: broken selector or JS-dependent listing —
        # indistinguishable without a render the crawl (on AUTO, per
        # ADR-0039) would never make. Zero links in fully rendered HTML is
        # unambiguous, so a rendered fetch stays silent.
        notices = (ZERO_LINKS_STATIC,)

    return DryRunReport(
        matched=matched,
        rejected=discovery.rejected,
        mega_menu=finding,
        projected_urls_at_max_depth=_projection(
            counts.get("product_links", 0),
            counts.get("next_page", 0),
            counts.get("subcategory_links", 0),
            max_depth,
        ),
        fetch_path=fetched.fetch_path,
        http_status=fetched.http_status,
        final_url=fetched.final_url,
        notices=notices,
    )


def _projection(products: int, next_pages: int, subcategories: int, max_depth: int) -> int:
    """The multiplicative fan-out estimate (spec 004 §4's formula).

    From the report's own matched counts: `products` are leaf links, and
    `next_page` + `subcategories` are links into pages that expand further
    — the model's one constant is that a product template discovers nothing
    (spec 001 §1). Each listing at depth `k < max_depth` contributes `t`
    URLs at `k + 1`, of which `f` are listings (`f ** k` of them at depth
    `k`), which gives the geometric sum. Same inputs, same number, always.
    """
    t = products + next_pages + subcategories
    f = next_pages + subcategories
    if f > 1:
        # 1 + f + … + f**(D-1) is a sum of integers, so the division is
        # exact, not rounding. `int()` because typeshed's `int.__pow__` is
        # declared `-> Any`, not because the value might not be one.
        return t * int(f**max_depth - 1) // (f - 1)
    if f == 1:
        return t * max_depth
    return t


def _nothing(page: Fetcher, notice: str) -> DryRunReport:
    """The report for a page nobody fetched: no status, no final URL, no
    matches — and the notice that says why."""
    return DryRunReport(
        matched={},
        rejected={},
        mega_menu=None,
        projected_urls_at_max_depth=0,
        # The path the crawl would have used, so an empty report still
        # names the posture the operator configured.
        fetch_path=page.path,
        http_status=None,
        final_url="",
        notices=(notice,),
    )
