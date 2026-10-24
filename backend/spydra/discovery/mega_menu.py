"""The mega-menu guard: is one rule discovering the whole tree? (spec 004 §3a).

A mega-menu lists the entire category tree on every page, so a
`subcategory_links` rule scoped to `nav a` discovers the whole site from
depth 0, defeats the depth cap, and looks like a working rule until the URL
cap fails the run. The shape is recognised **structurally, not by counting
links**: a count threshold fires on a 40-tile section page and sleeps on a
three-category site, while branch-and-level structure is what actually
separates "one container's tiles" from "the site tree" — and what the
operator explanation describes (BUILD_PLAN 2.6).

Pure, and the one analysis the dry-run (2.10) calls for its report. Nothing
here scopes a rule or rejects a link at runtime; the finding is advice —
"scope the selector to the menu's own container" (spec 004 §3a). Two blind
spots are deliberate, and §3a's "prefer the path already in the crawl"
projection — which the dry-run computes separately — is the backstop for
both: a site-wide menu nested under one top-level branch (one spanning
root), and a menu that also links the site's home, as real menus do: the
home path (Halden's `/shop/`, a breadcrumb's target) is an ancestor of
every accepted path, becomes the sole root, and the finding cannot fire for
the same broken rule that fires on pages without the home link.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from spydra.discovery.links import Discovery
from spydra.domain.urls import canonical_url

# Derived from the two Halden shapes (BUILD_PLAN 2.6): the mega-menu spans
# three branches from depth 0 (`nav a` on `/shop/cutting/` — fire), while
# scoped tiles are flat under every container (`section.subcategories` on
# `/shop/grinding/belts/` is two roots, neither spanning — stay silent).
# Two spanning roots is the smallest threshold that separates them; plain
# root-counting would fire on every two-tile container, the false positive
# this guard exists to prevent.
_SPANNING_ROOTS = 2
# The sample an operator reads: three branch names say "site-wide menu";
# one would leave them guessing which container leaked.
_ROOT_SAMPLE = 3


@dataclass(frozen=True, slots=True)
class MegaMenuFinding:
    """What the dry-run renders as: _"From this one page, this rule matched
    both a category and its own subcategories under N separate branches — a
    site-wide menu's shape, not one section's tiles; scope the selector to
    the menu's own container."_

    `roots` is that operator sample: up to `_ROOT_SAMPLE` spanning roots,
    sorted. `branches` is how many there are in all.
    """

    links: int
    paths: int
    branches: int
    levels: int
    roots: tuple[str, ...]


def whole_tree(discovery: Discovery) -> MegaMenuFinding | None:
    """The whole-tree finding for a discovery, or `None` when the rule's
    links do not span the site's category tree.

    Reads only `accepted["subcategory_links"]` (spec 004 §3a names that
    rule; a product rule matching a nav is a broken selector the
    count/sample report already exposes). Accepted links, not raw selector
    matches: what the rule *enqueues* is the hazard, and `allow_patterns`
    that narrow a mega-menu to one branch rightly keep this silent.
    """
    accepted = discovery.accepted.get("subcategory_links") or ()
    if not accepted:
        return None
    # Canonical paths only, deduped: tree structure never lives in the
    # query, so facet spellings and canonical pairs of one page must
    # collapse to a single node or a facet trap would fake nesting
    # (spec 004 §2 step 6 — no trailing slash, so the segment is the
    # boundary below).
    paths = {urlsplit(canonical_url(url)).path for url, _ in accepted}
    spanning = sorted(p for p in paths if _is_root(p, paths) and _spans(p, paths))
    if len(spanning) < _SPANNING_ROOTS:
        return None
    return MegaMenuFinding(
        links=len(accepted),
        paths=len(paths),
        branches=len(spanning),
        # Ancestors of one path nest (a prefix forest), so the largest
        # ancestor count anywhere is the longest ancestor→descendant chain.
        levels=max(1 + sum(_is_ancestor(q, p) for q in paths) for p in paths),
        roots=tuple(spanning[:_ROOT_SAMPLE]),
    )


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """Strict ancestry at a segment boundary: `ancestor != descendant` and
    `descendant == ancestor + "/" + rest`. Canonical paths carry no trailing
    slash (spec 004 §2 step 6), so the `/` is the boundary — `/shop/cutting`
    does not own `/shop/cutting-tools`. `/` owns every other path.
    """
    if ancestor == descendant:
        return False
    return descendant.startswith(ancestor if ancestor == "/" else ancestor + "/")


def _is_root(path: str, paths: set[str]) -> bool:
    """No accepted path sits above `path`."""
    return not any(_is_ancestor(other, path) for other in paths)


def _spans(path: str, paths: set[str]) -> bool:
    """Some accepted path sits strictly below `path`: a real parent, not a
    leaf spelling."""
    return any(_is_ancestor(path, other) for other in paths)
