"""The structural trap rejects in `discover` (BUILD_PLAN 2.5, spec 004 §1
rules 7–9, §3).

**Fired, not just survived.** A crawl that finishes could have been stopped
by anything; every test here names the reject reason, its count and a
sample for the trap shape that must trip it — and, as important, proves
each defence does NOT fire on the near shape that would make it a hazard to
an honest site: two cycles of pagination are not a loop, a 2,000-character
URL is not over the limit, a three-digit "month" is not a calendar, and an
`allow_pattern` is the operator's explicit yes that walks past the calendar
check while length and repetition still hold.

The trap shapes come from the catalogue's own traps (2.1) and 1.4's
`/trap/` server. The near shapes Halden does not carry are spliced into the
root's footer the way `test_links.py`'s unparseable test splices broken
hrefs — the one sanctioned hand-edit, so the fixture stays one site every
suite shares.
"""

import urllib.request
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

import pytest

from spydra.discovery.links import Discovery, RejectReason
from spydra.domain.entities import DiscoveryRules
from spydra.domain.urls import canonical_url
from tests.discovery.test_links import BASE, ROOT, rejected, run
from tests.fixtures.catalogue import HOST, LONG_URL_LENGTH
from tests.fixtures.server import FixtureSite

NEWS = "/shop/news/2026/10"
SEARCH = f"{BASE}/shop/search?q="
TRAP = "/trap/"


def search_url(chars: int) -> str:
    """An absolute search URL whose canonical form is exactly `chars`
    characters: `q` is a real parameter, so canonicalisation keeps it and
    only the padding moves."""
    url = SEARCH + "x" * (chars - len(SEARCH))
    assert len(canonical_url(url)) == chars
    return url


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


def with_footer(get: Callable[[str], str], *hrefs: str) -> str:
    """The root page with extra links spliced into its footer — the one
    sanctioned hand-edit (`test_links.py`'s unparseable test): a near shape
    Halden does not carry, without changing every listing page for every
    other suite."""
    footer = '<footer class="site-footer">'
    extra = "".join(f'<a href="{h}">x</a>' for h in hrefs)
    html = get(ROOT).replace(footer, footer + extra)
    assert extra in html, "the footer's markup changed; the splice missed"
    return html


def footer_rules(allow: tuple[str, ...] = ()) -> DiscoveryRules:
    """A rule that reaches the footer every listing page carries — the
    established way in (2.3's test pattern)."""
    return DiscoveryRules(subcategory_links="footer.site-footer a", allow_patterns=allow)


def path_of(url: str) -> str:
    """Canonical path+query, however the link was spelled."""
    parts = urlsplit(canonical_url(url))
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def kept(found: Discovery) -> set[str]:
    """The canonical path+query of every accepted link."""
    return {path_of(url) for url, _ in found.links()}


# ---------------------------------------------------------------------------
# calendar (spec 004 §1 rule 8, §3) — and the allow escape
# ---------------------------------------------------------------------------


def test_the_footers_calendar_link_is_rejected_as_calendar(
    get: Callable[[str], str],
) -> None:
    """`/shop/news/2026/10/` is at depth 1 from the seed — below the depth
    cap, so only the calendar reject stops it. The sample is the canonical
    spelling: no trailing slash (spec 004 §2 step 6), which is exactly the
    month-leaf form the pattern's boundary must match."""
    found = run(get, ROOT, footer_rules())

    tally = rejected(found, RejectReason.CALENDAR)
    assert tally is not None and tally.count == 1
    assert list(tally.samples) == [f"{BASE}{NEWS}"]
    assert f"{BASE}{NEWS}" not in [u for u, _ in found.links()]


def test_a_calendar_month_with_more_path_after_it_is_rejected_too(
    get: Callable[[str], str],
) -> None:
    """/2026/10/story is the same trap wearing an article path: the pattern
    anchors on the month's end (`/` or end of path), not on the URL's."""
    found = run(get, ROOT, footer_rules(), html=with_footer(get, f"{NEWS}/late-post"))

    tally = rejected(found, RejectReason.CALENDAR)
    assert tally is not None and tally.count == 2  # the footer's own and the splice
    assert f"{BASE}{NEWS}/late-post" in tally.samples


def test_date_like_paths_that_are_not_calendars_are_kept(
    get: Callable[[str], str],
) -> None:
    """A year the pattern does not name (1999) and a three-digit "month"
    (100) are date-like and nothing else: keeping them is what stops the
    defence swallowing honest archive paths."""
    found = run(
        get,
        ROOT,
        footer_rules(),
        html=with_footer(get, "/shop/news/1999/10/", "/shop/news/2026/100/"),
    )

    tally = rejected(found, RejectReason.CALENDAR)
    assert tally is not None and tally.count == 1, "a near shape was called a calendar"
    assert "/shop/news/1999/10" in kept(found)
    assert "/shop/news/2026/100" in kept(found)


def test_an_allow_pattern_is_the_calendars_escape(get: Callable[[str], str]) -> None:
    """The paired control to the calendar reject: the same link, the same
    rules, plus `allow_patterns = ["^/shop/news/"]` — the operator's
    reviewed yes (spec 004 §1 rule 3) outranks the calendar defence, which
    is why the calendar check runs after the allow check."""
    found = run(get, ROOT, footer_rules(allow=(r"^/shop/news/",)))

    assert rejected(found, RejectReason.CALENDAR) is None
    assert "/shop/news/2026/10" in kept(found)


def test_length_and_repetition_hold_even_for_an_allowed_link(
    get: Callable[[str], str],
) -> None:
    """The escape is the calendar's alone. A broad allow does not shorten a
    URL or unrepeat a path: those are facts about the link's own shape, so
    an explicitly allowed trap link is still refused (spec 004 §1)."""
    found = run(
        get,
        ROOT,
        footer_rules(allow=(r"^/shop/",)),
        html=with_footer(get, "/shop/t/t/t/"),
    )

    assert rejected(found, RejectReason.TOO_LONG) is not None, "the allow saved the link"
    assert rejected(found, RejectReason.REPEATING_PATH) is not None
    assert "/shop/t/t/t" not in kept(found)


# ---------------------------------------------------------------------------
# too_long (spec 004 §1 rule 7) — canonical, not raw
# ---------------------------------------------------------------------------


def test_the_footers_search_link_is_rejected_as_too_long(
    get: Callable[[str], str],
) -> None:
    found = run(get, ROOT, footer_rules())

    tally = rejected(found, RejectReason.TOO_LONG)
    assert tally is not None and tally.count == 1
    (sample,) = tally.samples
    assert sample == canonical_url(f"{SEARCH}{'x' * LONG_URL_LENGTH}")
    assert len(sample) > 2000


def test_the_length_limit_is_measured_on_the_canonical_spelling(
    get: Callable[[str], str],
) -> None:
    """Spec 004 §1 rule 7: "at most 2,000 characters" on the canonical
    spelling — the one hashed and enqueued. So 2,000 exactly is kept, 2,001
    is refused, and a href padded past the limit by tracking parameters is
    not a trap: canonicalisation has already stripped them."""
    padded = search_url(1950) + "&utm_source=" + "y" * 200
    assert len(padded) > 2000 and len(canonical_url(padded)) == 1950
    found = run(
        get,
        ROOT,
        footer_rules(),
        html=with_footer(get, search_url(2001), search_url(2000), padded),
    )

    tally = rejected(found, RejectReason.TOO_LONG)
    assert tally is not None and tally.count == 2  # the footer's own and the 2,001 one
    assert search_url(2001) in tally.samples
    assert path_of(search_url(2000)) in kept(found)
    assert path_of(padded) in kept(found), "a tracking-padded href is not a trap"


# ---------------------------------------------------------------------------
# repeating_path (spec 004 §1 rule 9, §3) — both unit shapes
# ---------------------------------------------------------------------------


LOOP = "/shop/loop/x/page"


def test_the_loop_terminates_at_the_third_pair(get: Callable[[str], str]) -> None:
    """The k=2 page's tile resolves to `loop,x` ×3. Rejected as
    `repeating_path` with a sample — and at link depth 3 under `max_depth`
    5, so depth is not the rejecter doing the work."""
    found = run(
        get,
        "/shop/loop/x/loop/x/page",
        DiscoveryRules(subcategory_links="section.subcategories a"),
        depth=2,
    )

    tally = rejected(found, RejectReason.REPEATING_PATH)
    assert tally is not None and tally.count == 1
    assert list(tally.samples) == [f"{BASE}/shop/loop/x/loop/x/loop/x/page"]
    assert rejected(found, RejectReason.DEPTH) is None
    assert found.links() == []


def test_two_cycles_are_honest_pagination_and_a_25_cycle_path_is_kept(
    get: Callable[[str], str],
) -> None:
    """The near shapes. `/a/b/a/b/` is what honest pagination looks like,
    and spec 004 §3's own bug-family example `/a/b/a/b/a/` (2.5 cycles)
    does not trip — the third FULL repetition does."""
    one = run(get, LOOP, DiscoveryRules(subcategory_links="section.subcategories a"))
    assert one.links() == [(f"{BASE}/shop/loop/x/loop/x/page", 1)]
    assert rejected(one, RejectReason.REPEATING_PATH) is None

    found = run(get, ROOT, footer_rules(), html=with_footer(get, "/shop/loop/x/loop/x/loop/"))
    assert rejected(found, RejectReason.REPEATING_PATH) is None
    assert "/shop/loop/x/loop/x/loop" in kept(found)


def test_the_single_segment_trap_is_rejected_at_the_third_deeper(
    get: Callable[[str], str],
) -> None:
    """1.4's `/trap/`: every page links one more `deeper`. Two hops are
    ordinary nesting; the third full repetition is the relative-link bug's
    shape whatever the repeated unit (spec 004 §3)."""
    two = run(get, f"{TRAP}deeper/", DiscoveryRules(subcategory_links="a"))
    assert two.links() == [(f"{BASE}{TRAP}deeper/deeper/", 1)]  # fetchable: as written
    assert rejected(two, RejectReason.REPEATING_PATH) is None

    three = run(get, f"{TRAP}deeper/deeper/", DiscoveryRules(subcategory_links="a"), depth=2)
    tally = rejected(three, RejectReason.REPEATING_PATH)
    assert tally is not None and tally.count == 1
    assert list(tally.samples) == [f"{BASE}{TRAP}deeper/deeper/deeper"]
    assert rejected(three, RejectReason.DEPTH) is None
    assert three.links() == []
