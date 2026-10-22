"""A URL's identity: spec 004 §2 steps 1–6 and `url_hash` (BUILD_PLAN 2.2).

Each step is pinned on its own, so breaking one step turns its own tests red
rather than a single end-to-end string that cannot say which step went
wrong. Both directions are held where it matters: what a step must remove,
and what it must leave alone. A canonicaliser that is too eager collapses
two pages into one, and the second is never crawled. That is as silent as
crawling one page twice.

`url_hash` is asserted as `sha256(canonical_url(x))` and by the two
acceptance criteria spec 004 §5 names. Nothing here pins a particular digest.
"""

import hashlib

import pytest

from spydra.domain.urls import canonical_url, fetchable_url, url_hash

H = "http://halden.test"

# ---------------------------------------------------------------------------
# Step 1: lowercase scheme and host; strip the default port
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTP://halden.test/shop", f"{H}/shop"),
        ("http://HALDEN.Test/shop", f"{H}/shop"),
        ("HtTpS://Halden.TEST/shop", "https://halden.test/shop"),
    ],
)
def test_scheme_and_host_are_lowercased(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


def test_the_path_keeps_its_case() -> None:
    """Only scheme and host are case-insensitive. Most servers route paths by
    case, so `/Shop/Discs` and `/shop/discs` can be two pages."""
    assert canonical_url("http://halden.test/Shop/Discs") == f"{H}/Shop/Discs"


def test_the_query_keeps_its_case() -> None:
    assert canonical_url(f"{H}/shop?Colour=Red") == f"{H}/shop?Colour=Red"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://halden.test:80/shop", f"{H}/shop"),
        ("https://halden.test:443/shop", "https://halden.test/shop"),
        ("HTTP://HALDEN.TEST:80/shop", f"{H}/shop"),
    ],
)
def test_the_default_port_is_stripped(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://halden.test:8080/shop",
        # The other scheme's default is not this scheme's default.
        "http://halden.test:443/shop",
        "https://halden.test:80/shop",
    ],
)
def test_a_port_that_is_not_the_schemes_default_is_kept(url: str) -> None:
    assert canonical_url(url) == url


def test_a_bracketed_ipv6_host_keeps_its_brackets() -> None:
    """`[::1]:8080` without brackets is `::1:8080`, which is not a URL a
    fetcher can parse: the port would read as part of the address."""
    assert canonical_url("http://[::1]:8080/shop") == "http://[::1]:8080/shop"


# ---------------------------------------------------------------------------
# Credentials: never part of a page's identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@halden.test/shop",
        "http://user@halden.test/shop",
        "http://user:secret@HALDEN.TEST:80/shop",
    ],
)
def test_credentials_in_a_link_are_dropped(url: str) -> None:
    """Kept, they would be written into the queue, the pages table and the
    logs (spec 009 §1 forbids logging a credential)."""
    canonical = canonical_url(url)
    assert canonical == f"{H}/shop"
    assert "secret" not in canonical
    assert "@" not in canonical


def test_credentials_are_dropped_with_a_non_default_port_kept() -> None:
    assert canonical_url("https://u:p@halden.test:8443/shop") == "https://halden.test:8443/shop"


# ---------------------------------------------------------------------------
# Step 2: dot segments resolved; duplicate slashes collapsed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/shop/./cutting", "/shop/cutting"),
        ("/shop/cutting/../finishing", "/shop/finishing"),
        ("/shop/cutting/./discs/../discs", "/shop/cutting/discs"),
        ("/shop/a/b/../../cutting", "/shop/cutting"),
        # RFC 3986 §5.2.4: `..` above the root goes nowhere.
        ("/../shop", "/shop"),
    ],
)
def test_dot_segments_are_resolved(path: str, expected: str) -> None:
    assert canonical_url(f"{H}{path}") == f"{H}{expected}"


@pytest.mark.parametrize(
    "path",
    [
        # Dots inside a segment are a name, not a dot segment.
        "/shop/..discs/x",
        "/shop/discs../x",
        "/shop/v1.2/x",
        "/shop/.hidden/x",
    ],
)
def test_dots_inside_a_segment_are_not_dot_segments(path: str) -> None:
    assert canonical_url(f"{H}{path}") == f"{H}{path}"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/shop//cutting", "/shop/cutting"),
        ("/shop///cutting////discs", "/shop/cutting/discs"),
        ("//shop/cutting", "/shop/cutting"),
    ],
)
def test_duplicate_slashes_are_collapsed(path: str, expected: str) -> None:
    assert canonical_url(f"{H}{path}") == f"{H}{expected}"


def test_slashes_in_the_query_are_not_paths() -> None:
    """Step 2 is about the path. A query value containing `//` or `/../` is
    data, and the site may need it as written."""
    url = f"{H}/go?next=a//b/../c"
    assert canonical_url(url) == url


# ---------------------------------------------------------------------------
# Step 3: the fragment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{H}/shop#top", f"{H}/shop"),
        (f"{H}/shop?page=2#reviews", f"{H}/shop?page=2"),
        (f"{H}/shop#", f"{H}/shop"),
        (f"{H}/#section", f"{H}/"),
    ],
)
def test_the_fragment_is_stripped(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


# ---------------------------------------------------------------------------
# Step 4: tracking parameters
# ---------------------------------------------------------------------------

TRACKING = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    # A prefix, not a list: anything a campaign tool invents under `utm_`.
    "utm_whatever_next",
    "gclid",
    "fbclid",
    "msclkid",
    "ref",
    "_ga",
    "mc_cid",
    "mc_eid",
]


@pytest.mark.parametrize("name", TRACKING)
def test_each_tracking_parameter_is_stripped_and_the_rest_survive(name: str) -> None:
    url = f"{H}/shop/discs?page=2&{name}=abc"
    assert canonical_url(url) == f"{H}/shop/discs?page=2"


@pytest.mark.parametrize("name", TRACKING)
def test_a_url_with_only_tracking_parameters_has_no_query_left(name: str) -> None:
    assert canonical_url(f"{H}/shop/discs?{name}=abc") == f"{H}/shop/discs"


@pytest.mark.parametrize("name", ["gclid", "utm_source"])
def test_a_tracking_parameter_with_a_blank_value_is_still_stripped(name: str) -> None:
    assert canonical_url(f"{H}/shop?{name}=&page=2") == f"{H}/shop?page=2"


def test_every_tracking_parameter_at_once_is_stripped() -> None:
    query = "&".join(f"{name}=x" for name in TRACKING)
    assert canonical_url(f"{H}/shop?{query}&page=2") == f"{H}/shop?page=2"


@pytest.mark.parametrize(
    "escaped",
    [
        "utm%5Fsource",  # `_` escaped
        "utm%5fsource",  # lower-case hex is the same octet
        "%75tm_source",  # `u` escaped
        "%67clid",  # `g` escaped
        "%5Fga",  # `_` escaped at the start
        "m%63_cid",
    ],
)
def test_an_escaped_tracking_key_is_still_tracking(escaped: str) -> None:
    """A key is a key however it is percent-encoded; a site or a mail tool
    that escapes one more character than it needs to does not get a fresh
    page identity per click."""
    assert canonical_url(f"{H}/shop?page=2&{escaped}=x") == f"{H}/shop?page=2"


@pytest.mark.parametrize(
    "name",
    [
        "page",
        # Look-alikes: the list is whole names plus one prefix, nothing fuzzier.
        "reference",
        "referrer",
        "prefix",
        "utm",
        "xutm_source",
        "ga",
        "gclid_id",
        "mc_cidx",
    ],
)
def test_a_parameter_that_is_not_tracking_survives(name: str) -> None:
    url = f"{H}/shop?{name}=2"
    assert canonical_url(url) == url


# ---------------------------------------------------------------------------
# Step 5: sort, by key then value, as written
# ---------------------------------------------------------------------------


def test_parameters_are_sorted_by_key() -> None:
    assert canonical_url(f"{H}/shop?b=2&a=1") == f"{H}/shop?a=1&b=2"
    assert canonical_url(f"{H}/shop?per_page=25&colour=red") == (f"{H}/shop?colour=red&per_page=25")


def test_a_repeated_key_is_sorted_by_value() -> None:
    """Key first, then value: a repeated key's values are ordered among
    themselves without being separated by the other keys."""
    assert canonical_url(f"{H}/shop?size=m&colour=red&size=l&colour=blue") == (
        f"{H}/shop?colour=blue&colour=red&size=l&size=m"
    )


def test_repeated_keys_are_all_kept() -> None:
    """Sorting is not deduplicating: `?size=l&size=m` is a two-value filter."""
    assert canonical_url(f"{H}/shop?size=m&size=l") == f"{H}/shop?size=l&size=m"


@pytest.mark.parametrize(
    "pair",
    [
        "path=%2Fshop%2Fcutting",  # `%2F` must not become `/`
        "q=a+b",  # `+` must not become `%20`
        "q=a%20b",  # `%20` must not become `+`
        "q=caf%C3%A9",  # an encoded non-ASCII value stays encoded
        "q=%7E",  # even an escape of an unreserved character
    ],
)
def test_a_value_is_kept_exactly_as_written(pair: str) -> None:
    """A site that spells `%2F` may route on that spelling; decoding and
    re-encoding would be a different URL that merely looks the same."""
    assert canonical_url(f"{H}/shop?{pair}&a=1") == f"{H}/shop?a=1&{pair}"


def test_a_blank_value_is_kept() -> None:
    assert canonical_url(f"{H}/shop?b=&a=1") == f"{H}/shop?a=1&b="


def test_a_blank_value_alone_is_kept() -> None:
    assert canonical_url(f"{H}/shop?q=") == f"{H}/shop?q="


# ---------------------------------------------------------------------------
# Step 6: the trailing slash, except at the root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{H}/shop/cutting/discs/", f"{H}/shop/cutting/discs"),
        (f"{H}/shop/", f"{H}/shop"),
        (f"{H}/shop/discs/?page=2", f"{H}/shop/discs?page=2"),
        (f"{H}/shop/discs/#top", f"{H}/shop/discs"),
    ],
)
def test_a_trailing_slash_is_stripped(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{H}/", f"{H}/"),
        (H, f"{H}/"),
        (f"{H}/?page=2", f"{H}/?page=2"),
        ("HTTP://HALDEN.TEST:80/", f"{H}/"),
        (f"{H}//", f"{H}/"),
        (f"{H}/./", f"{H}/"),
    ],
)
def test_the_root_keeps_its_slash(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


# ---------------------------------------------------------------------------
# Idempotence: a canonical URL is its own canonical form
# ---------------------------------------------------------------------------

SPELLINGS = [
    "HTTP://Halden.TEST:80/shop/cutting/./discs/../discs//?utm_source=n&b=2&a=1#top",
    "https://u:p@halden.test:443/shop/",
    "http://halden.test:8080/Shop/Discs/",
    f"{H}/shop/discs?per_page=25&colour=red",
    f"{H}/shop/discs?path=%2Fx&q=a+b&r=a%20b&blank=",
    f"{H}/shop/discs?size=m&size=l&colour=red",
    f"{H}/shop/discs?%67clid=x&utm%5Fsource=y&page=2",
    f"{H}/../shop//x/",
    f"{H}/shop/..discs/v1.2/",
    f"{H}/go?next=a//b/../c",
    f"{H}",
    f"{H}/?page=2#x",
    *(f"{H}/shop?page=2&{name}=abc" for name in TRACKING),
]


@pytest.mark.parametrize("url", SPELLINGS)
def test_canonical_url_is_idempotent(url: str) -> None:
    once = canonical_url(url)
    assert canonical_url(once) == once


@pytest.mark.parametrize("url", SPELLINGS)
def test_url_hash_of_a_canonical_url_is_the_hash_of_any_spelling(url: str) -> None:
    assert url_hash(canonical_url(url)) == url_hash(url)


# ---------------------------------------------------------------------------
# url_hash (spec 004 §2, §5; spec 001 §1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", SPELLINGS)
def test_url_hash_is_sha256_of_the_canonical_url(url: str) -> None:
    assert url_hash(url) == hashlib.sha256(canonical_url(url).encode("utf-8")).digest()


def test_parameter_order_does_not_change_the_hash() -> None:
    """Spec 004 §5: `?b=2&a=1` and `?a=1&b=2` produce the same `url_hash`."""
    assert url_hash(f"{H}/shop?b=2&a=1") == url_hash(f"{H}/shop?a=1&b=2")


def test_utm_source_is_stripped_while_page_2_survives() -> None:
    """Spec 004 §5: `utm_source` is stripped; a meaningful `?page=2` is not."""
    base = f"{H}/shop/cutting/discs"
    tracked = f"{base}?page=2&utm_source=newsletter"

    assert url_hash(tracked) == url_hash(f"{base}?page=2")
    assert url_hash(tracked) != url_hash(base)
    assert url_hash(f"{base}?utm_source=newsletter") == url_hash(base)


@pytest.mark.parametrize(
    ("one", "other"),
    [
        (f"{H}/shop/discs?page=2", f"{H}/shop/discs?page=3"),
        (f"{H}/shop/discs", f"{H}/shop/discs?page=2"),
        (f"{H}/shop/discs", f"{H}/shop/Discs"),
        (f"{H}/shop/discs", "https://halden.test/shop/discs"),
        (f"{H}/shop/discs", "http://halden.test:8080/shop/discs"),
        (f"{H}/shop/discs?path=%2Fx", f"{H}/shop/discs?path=/x"),
        (f"{H}/shop/discs?q=", f"{H}/shop/discs"),
    ],
)
def test_two_different_pages_hash_differently(one: str, other: str) -> None:
    """The other half: a canonicaliser that collapses these has made one of
    two pages uncrawlable, silently."""
    assert url_hash(one) != url_hash(other)


def test_url_hash_is_a_sha256_digest() -> None:
    digest = url_hash(f"{H}/shop")
    assert isinstance(digest, bytes)
    assert len(digest) == hashlib.sha256().digest_size


# ---------------------------------------------------------------------------
# Absolute URLs only (2.2 review, finding 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "example.com/a",
        "halden.test/shop",
        "/shop/cutting/discs",
        "shop/cutting/discs",
        "?page=2",
        "mailto:x@y",
        "http:///shop",
        "",
    ],
)
def test_a_url_with_no_scheme_or_no_host_is_refused(url: str) -> None:
    """Accepted, `example.com/a` becomes `/example.com/a` and `mailto:x@y`
    becomes `mailto:/x@y`: paths that look valid and hash as pages."""
    with pytest.raises(ValueError):
        canonical_url(url)


def test_url_hash_refuses_what_canonical_url_refuses() -> None:
    with pytest.raises(ValueError):
        url_hash("example.com/a")


# ---------------------------------------------------------------------------
# Hosts: IDNA and the trailing dot (2.2 review, finding 6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://BÜCHER.de./shop",
        "http://bücher.de/shop",
        "http://xn--bcher-kva.de/shop",
        "http://XN--BCHER-KVA.DE./shop",
        "http://xn--bcher-kva.de.:80/shop",
    ],
)
def test_an_idn_host_in_any_spelling_is_one_ascii_host(url: str) -> None:
    assert canonical_url(url) == "http://xn--bcher-kva.de/shop"


def test_a_trailing_dot_on_the_host_is_dropped() -> None:
    assert canonical_url("http://halden.test./shop") == f"{H}/shop"


def test_an_idn_canonical_is_idempotent() -> None:
    once = canonical_url("http://BÜCHER.de./shop/")
    assert canonical_url(once) == once


# ---------------------------------------------------------------------------
# Deterministic ties in the sort (2.2 review, finding 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("one", "other"),
    [
        # Decode alike, spelled differently: the order written must not
        # decide the canonical.
        ("q=a+b&q=a%20b", "q=a%20b&q=a+b"),
        ("a&a=", "a=&a"),
        ("%61=1&a=1", "a=1&%61=1"),
        ("x=1&q=a+b&q=a%20b", "q=a%20b&x=1&q=a+b"),
    ],
)
def test_a_tie_between_spellings_sorts_the_same_either_way(one: str, other: str) -> None:
    assert canonical_url(f"{H}/shop?{one}") == canonical_url(f"{H}/shop?{other}")
    assert url_hash(f"{H}/shop?{one}") == url_hash(f"{H}/shop?{other}")


def test_a_tie_keeps_both_spellings_as_written() -> None:
    canonical = canonical_url(f"{H}/shop?q=a%20b&q=a+b")
    assert sorted(canonical.split("?", 1)[1].split("&")) == ["q=a%20b", "q=a+b"]


# ---------------------------------------------------------------------------
# fetchable_url: what the queue requests (2.2 review, finding 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"{H}/shop/cutting/discs/",
        f"{H}/Shop/Discs",
        f"{H}/shop/./cutting//discs/../discs/",
        f"{H}/shop?b=2&a=1",
        f"{H}/shop?utm_source=newsletter&ref=home&gclid=1",
        f"{H}/shop?path=%2Fx&q=a+b&blank=",
        "http://halden.test:8080/shop",
        "http://HALDEN.TEST/shop",
        "https://halden.test:443/shop",
        f"{H}/",
    ],
)
def test_fetchable_url_keeps_path_query_case_and_port_as_written(url: str) -> None:
    """Canonicalisation is for the hash; the request goes out as the site
    wrote the link, or a site that 301s `/x` to `/x/` costs a redirect per
    page and one that 404s `/x` is unreachable."""
    assert fetchable_url(url) == url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{H}/shop#top", f"{H}/shop"),
        (f"{H}/shop/?b=2&a=1#reviews", f"{H}/shop/?b=2&a=1"),
        (f"{H}/shop#", f"{H}/shop"),
    ],
)
def test_fetchable_url_drops_the_fragment(url: str, expected: str) -> None:
    assert fetchable_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://user:secret@halden.test/shop/", f"{H}/shop/"),
        ("http://user@halden.test/shop", f"{H}/shop"),
        ("http://u:p@halden.test:8080/Shop?b=1#x", "http://halden.test:8080/Shop?b=1"),
        # An `@` in the password is still the password.
        ("http://u:p@ss@halden.test/shop", f"{H}/shop"),
    ],
)
def test_fetchable_url_drops_credentials(url: str, expected: str) -> None:
    assert fetchable_url(url) == expected


@pytest.mark.parametrize("url", SPELLINGS)
def test_fetchable_url_hashes_the_same_as_the_url_it_came_from(url: str) -> None:
    """The queue stores the fetchable spelling under the original's hash; the
    two must agree or a re-enqueue of the stored URL is a second row."""
    assert url_hash(fetchable_url(url)) == url_hash(url)


@pytest.mark.parametrize("url", ["example.com/a", "/shop", "mailto:x@y"])
def test_fetchable_url_refuses_a_url_with_no_scheme_or_host(url: str) -> None:
    with pytest.raises(ValueError):
        fetchable_url(url)
