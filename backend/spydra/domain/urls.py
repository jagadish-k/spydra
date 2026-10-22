"""A URL's identity: spec 004 §2's canonical form, and the hash of it.

**Getting this wrong is silent either way.** Too loose, and one page is
crawled under every spelling a site links it by: `?b=2&a=1`, `?a=1&b=2`, a
newsletter's `utm_source`, a fragment. Too tight, and two pages collapse into
one and the second is never crawled. Both look like a working crawl.

So there is exactly one definition, here, pure, and `url_hash` is defined
over it: a caller cannot hash a URL without canonicalising it first.

Steps 1–6 of spec 004 §2, in its order. Step 7 (`rel="canonical"`) needs the
page, so it lives with the parser (`spydra.discovery.canonical`) and calls
back into `canonical_url`.
"""

import hashlib
import posixpath
from typing import Final
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

# Spec 004 §2 step 4. `utm_` is a prefix; the rest are whole names.
_TRACKING: Final[frozenset[str]] = frozenset(
    {"gclid", "fbclid", "msclkid", "ref", "_ga", "mc_cid", "mc_eid"}
)
_TRACKING_PREFIX: Final[str] = "utm_"


def canonical_url(url: str) -> str:
    """Spec 004 §2 steps 1–6. Idempotent: canonicalising a canonical URL
    changes nothing.

    The query is sorted and filtered **as written**, never decoded and
    re-encoded: a site that spells a value `%2F` may route on that spelling,
    and rewriting it would be a different URL that merely looks the same.
    Only the key is decoded, to recognise a tracking parameter however it is
    escaped.

    **Absolute URLs only.** A relative URL, or one with no host, raises
    `ValueError` rather than being turned into a path that looks valid
    (`example.com/a` would otherwise become `/example.com/a`). Resolving a
    link against its page is the caller's job, before this. So does a bad
    netloc (`h:99999`, `[bad`): `urlsplit` raises, and that is the answer.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = _host(parts.hostname or "")
    if not scheme or not host:
        raise ValueError(f"not an absolute URL: {url!r}")
    port = parts.port
    # Rebuilt from host and port only, so `user:pass@` in a link is dropped:
    # credentials are never part of a page's identity, and keeping them would
    # write them into the queue and the logs.
    if ":" in host:
        # `hostname` drops an IPv6 literal's brackets; the URL needs them.
        host = f"[{host}]"
    netloc = host if port is None or port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, _path(parts.path), _query(parts.query), ""))


def fetchable_url(url: str) -> str:
    """The URL to request: as the site wrote it, minus what is never sent
    or must never be stored.

    Spec 004 §2 applies canonicalisation **before hashing**, not before
    fetching. A site that answers `/x` with a 301 to `/x/`, or a 404, or
    routes on `ref=`, would otherwise cost a redirect per page or be
    unreachable. So the queue fetches the discovered spelling, and only the
    hash and `pages.url` are canonical. Two things go regardless: the
    fragment (a client never sends it) and `user:pass@` (it would be stored
    in the queue and logged with every line about the page).
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.hostname:
        raise ValueError(f"not an absolute URL: {url!r}")
    netloc = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))


def url_hash(url: str) -> bytes:
    """`sha256(canonical_url(url))`, the key of `UNIQUE (domain_id,
    url_hash)` and `UNIQUE (run_id, url_hash)` (spec 001 §1, spec 004 §2).

    SHA-256 and not a cheaper digest because a collision here means a page
    silently never crawled, which is indistinguishable from a page that had
    nothing on it.
    """
    return hashlib.sha256(canonical_url(url).encode("utf-8")).digest()


def _host(hostname: str) -> str:
    """Lowercased, without a trailing dot, and in its ASCII (IDNA) form, so
    `BÜCHER.de` and `xn--bcher-kva.de` are one host."""
    host = hostname.lower().rstrip(".")
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise ValueError(f"not a valid host: {hostname!r}") from e


def _path(path: str) -> str:
    """Steps 2 and 6: dot segments resolved, duplicate slashes collapsed, a
    trailing slash stripped except at the root."""
    if not path:
        return "/"
    # normpath resolves `.`/`..` and collapses `//`, except a leading `//`,
    # which POSIX reserves and it keeps; lstrip takes that one.
    resolved = "/" + posixpath.normpath(path).lstrip("/")
    return resolved if resolved == "/" else resolved.rstrip("/")


def _query(query: str) -> str:
    """Steps 4 and 5: tracking parameters dropped, the rest sorted by key
    then value, each pair kept exactly as written."""
    pairs = [pair for pair in query.split("&") if pair]
    kept = [pair for pair in pairs if not _is_tracking(pair)]
    return "&".join(sorted(kept, key=_sort_key))


def _key(pair: str) -> str:
    return unquote_plus(pair.split("=", 1)[0])


def _is_tracking(pair: str) -> bool:
    key = _key(pair).lower()
    return key in _TRACKING or key.startswith(_TRACKING_PREFIX)


def _sort_key(pair: str) -> tuple[str, str, str]:
    """Decoded key, decoded value, then the pair as written: `q=a+b` and
    `q=a%20b` decode alike, and without the last element their order would
    be whatever order the page wrote them in."""
    key, _, value = pair.partition("=")
    return (unquote_plus(key), unquote_plus(value), pair)
