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
import re
from typing import Final
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

# Spec 004 §2 step 4. `utm_` is a prefix; the rest are whole names.
_TRACKING: Final[frozenset[str]] = frozenset(
    {"gclid", "fbclid", "msclkid", "ref", "_ga", "mc_cid", "mc_eid"}
)
_TRACKING_PREFIX: Final[str] = "utm_"

_SLASHES = re.compile(r"/{2,}")


def canonical_url(url: str) -> str:
    """Spec 004 §2 steps 1–6. Idempotent: canonicalising a canonical URL
    changes nothing.

    The query is sorted and filtered **as written**, never decoded and
    re-encoded: a site that spells a value `%2F` may route on that spelling,
    and rewriting it would be a different URL that merely looks the same.
    Only the key is decoded, to recognise a tracking parameter however it is
    escaped.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    # Rebuilt from host and port only, so `user:pass@` in a link is dropped:
    # credentials are never part of a page's identity, and keeping them would
    # write them into the queue and the logs.
    netloc = host if port is None or port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, _path(parts.path), _query(parts.query), ""))


def url_hash(url: str) -> bytes:
    """`sha256(canonical_url(url))`, the key of `UNIQUE (domain_id,
    url_hash)` and `UNIQUE (run_id, url_hash)` (spec 001 §1, spec 004 §2).

    SHA-256 and not a cheaper digest because a collision here means a page
    silently never crawled, which is indistinguishable from a page that had
    nothing on it.
    """
    return hashlib.sha256(canonical_url(url).encode("utf-8")).digest()


def _path(path: str) -> str:
    """Steps 2 and 6: dot segments resolved, duplicate slashes collapsed, a
    trailing slash stripped except at the root."""
    if not path:
        return "/"
    collapsed = _SLASHES.sub("/", path)
    resolved = posixpath.normpath(collapsed)
    # normpath keeps a leading "//" (POSIX allows it) and turns "/" into "/".
    resolved = "/" + resolved.lstrip("/")
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


def _sort_key(pair: str) -> tuple[str, str]:
    key, _, value = pair.partition("=")
    return (unquote_plus(key), unquote_plus(value))
