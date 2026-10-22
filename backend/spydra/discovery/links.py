"""What a page leads to, by the template's discovery rules (spec 004 §1).

**Pure, and the same function for the crawl and the dry-run.** The crawler
enqueues `accepted`; 2.10's dry-run reports both halves. A dry-run built on a
second implementation would approve rules the crawl then applies
differently, which is the drift ADR-0019 forbids for authoring.

Every dropped link carries the reason it was dropped. "Discovered 48, kept
12" is useless to an operator; "312 denied by `\\?(colour|grit)=`" is the
facet trap caught before a run (spec 004 §4).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from spydra.domain.entities import DiscoveryRules
from spydra.domain.urls import canonical_url, fetchable_url, url_hash

# Spec 004 §1's rule names, in the order a link is attributed: a product
# link that is also inside the subcategory container counts as a product.
RULES: tuple[str, ...] = ("product_links", "next_page", "subcategory_links")

_SAMPLES = 5
_SCHEMES = frozenset({"http", "https"})


class RejectReason(StrEnum):
    UNPARSEABLE = "unparseable"
    SCHEME = "scheme"
    OFF_HOST = "off_host"
    NOT_ALLOWED = "not_allowed"
    DENY_PATTERN = "deny_pattern"
    DEPTH = "depth"


@dataclass(frozen=True, slots=True)
class Rejected:
    """One reason's tally. `pattern` names the deny pattern that fired, so
    the report can say which pattern exploded (spec 004 §3)."""

    reason: RejectReason
    count: int
    samples: tuple[str, ...]
    pattern: str | None = None


@dataclass(frozen=True, slots=True)
class Discovery:
    """`accepted[rule]` is `(fetchable url, depth)` pairs, deduplicated
    across the whole page by canonical hash; `rejected` is keyed by reason,
    or by `deny_pattern:<pattern>` so two patterns are counted apart."""

    accepted: Mapping[str, tuple[tuple[str, int], ...]]
    rejected: Mapping[str, Rejected] = field(default_factory=dict)

    def links(self) -> list[tuple[str, int]]:
        """Every accepted link, in rule order: what the crawler enqueues."""
        return [link for rule in RULES for link in self.accepted.get(rule, ())]


def discover(
    html: str,
    page_url: str,
    rules: DiscoveryRules,
    *,
    host: str,
    depth: int,
    max_depth: int,
    domain_deny: Sequence[str] = (),
) -> Discovery:
    """The links `rules` select on this page, kept or rejected with a reason.

    `page_url` is the URL the body was served from (relative hrefs resolve
    against it). `host` is the domain's host: the only host followed.
    `depth` is this page's depth; its links are `depth + 1`, and the page
    expands only while `depth < max_depth` (spec 004 §1, §5).
    """
    allow = [re.compile(p) for p in rules.allow_patterns]
    deny = [re.compile(p) for p in (*domain_deny, *rules.deny_patterns)]
    own_host = _host_of(host)
    tally = _Tally()
    accepted: dict[str, list[tuple[str, int]]] = {}
    # Keyed by canonical hash for an http(s) link, by the resolved spelling
    # for anything else (it has no canonical form). Checked before any
    # tally, so a link two rules match is counted once, under the first.
    seen: set[bytes | str] = set()
    doc = LexborHTMLParser(html) if html else None

    for rule, href in _hrefs(doc, rules):
        absolute = urljoin(page_url, href) if _resolvable(page_url, href) else href
        scheme = _scheme(absolute)
        if scheme is None:
            if _first(seen, absolute):
                tally.add(RejectReason.UNPARSEABLE, href)
            continue
        if scheme not in _SCHEMES:
            # `mailto:`, `tel:`, `javascript:`: rule 2, checked before
            # canonicalising, which refuses anything without a host.
            if _first(seen, absolute):
                tally.add(RejectReason.SCHEME, href)
            continue
        try:
            canonical = canonical_url(absolute)
            digest = url_hash(absolute)
            fetchable = fetchable_url(absolute)
        except ValueError:
            if _first(seen, absolute):
                tally.add(RejectReason.UNPARSEABLE, href)
            continue
        if not _first(seen, digest):
            continue
        parts = urlsplit(canonical)
        target = parts.path + (f"?{parts.query}" if parts.query else "")

        if parts.netloc != own_host:
            tally.add(RejectReason.OFF_HOST, canonical)
        elif allow and not any(p.search(target) for p in allow):
            tally.add(RejectReason.NOT_ALLOWED, canonical)
        elif (hit := next((p for p in deny if p.search(target)), None)) is not None:
            tally.add(RejectReason.DENY_PATTERN, canonical, hit.pattern)
        elif depth >= max_depth:
            tally.add(RejectReason.DEPTH, canonical)
        else:
            accepted.setdefault(rule, []).append((fetchable, depth + 1))

    return Discovery(
        accepted={rule: tuple(links) for rule, links in accepted.items()},
        rejected=tally.result(),
    )


def _first(seen: set[bytes | str], key: bytes | str) -> bool:
    """True the first time `key` is seen on this page."""
    if key in seen:
        return False
    seen.add(key)
    return True


def _scheme(url: str) -> str | None:
    """The lowercased scheme, or `None` when `urlsplit` cannot parse it."""
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:
        return None


def _resolvable(page_url: str, href: str) -> bool:
    """`urljoin` raises on some malformed hrefs (`http://[bad`); those are
    resolved as written and rejected as unparseable below."""
    try:
        urljoin(page_url, href)
    except ValueError:
        return False
    return True


def _hrefs(doc: LexborHTMLParser | None, rules: DiscoveryRules) -> Iterable[tuple[str, str]]:
    if doc is None:
        return
    for rule in RULES:
        selector = getattr(rules, rule)
        if not selector:
            continue
        for node in doc.css(selector):
            href = (node.attributes.get("href") or "").strip()
            if href:
                yield rule, href


def _host_of(host: str) -> str:
    """The domain's host as `canonical_url` spells a netloc (lowercase,
    default port dropped, IDNA), so the comparison is like for like."""
    scheme = "https" if host.endswith(":443") else "http"
    return urlsplit(canonical_url(f"{scheme}://{host}/")).netloc


class _Tally:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._samples: dict[str, list[str]] = {}
        self._reasons: dict[str, tuple[RejectReason, str | None]] = {}

    def add(self, reason: RejectReason, url: str, pattern: str | None = None) -> None:
        key = f"{reason}:{pattern}" if pattern is not None else str(reason)
        self._reasons[key] = (reason, pattern)
        self._counts[key] = self._counts.get(key, 0) + 1
        samples = self._samples.setdefault(key, [])
        if len(samples) < _SAMPLES:
            samples.append(url)

    def result(self) -> dict[str, Rejected]:
        return {
            key: Rejected(
                reason=reason,
                count=self._counts[key],
                samples=tuple(self._samples[key]),
                pattern=pattern,
            )
            for key, (reason, pattern) in self._reasons.items()
        }
