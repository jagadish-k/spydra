"""Halden Tools: the discovery catalogue every phase-2 task is tested against.

BUILD_PLAN `2.1`. One invented host, one exact product set, and every
discovery shape spec 004 names: pagination, a facet explosion, a mega-menu
that links the whole tree from depth 0, a subcategory nest, hidden
subcategory tiles, canonical pairs, canonicalisation material, rejects and
three unbounded traps. Building it once, here, is what lets `2.2`–`2.10` and
the phase-2 exit test against the same site instead of each growing its own.

**Hand-written, then parameterised**, like `/generated/<n>`: the markup is
`pages/halden/{listing,product}.html`, written by hand, and this module only
fills their `{{slots}}`. A thousand committed files would be one shape copied
a thousand times, and could not express a facet space that never ends.

**Deterministic.** Every page is a pure function of its path, query and
`Host` header. A fixture that changed between two fetches would make dedupe
and change detection untestable.

Stdlib only, for the reason `server.py` gives: it also runs inside the
render sidecar's container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

PAGES = Path(__file__).resolve().parent / "pages" / "halden"
LISTING = PAGES / "listing.html"
PRODUCT = PAGES / "product.html"

PREFIX = "/shop/"
HOST = "halden.test"
PER_PAGE = 10


@dataclass(frozen=True)
class Node:
    """One category-tree node. A node with products is a leaf listing."""

    path: str  # "/shop/cutting/discs/"
    title: str
    code: str  # SKU stem
    products: int = 0
    children: tuple[Node, ...] = ()
    # Spec 004 §3a case A: tiles in the HTML, hidden by CSS.
    hidden_tiles: bool = False
    # Product links in category context, whose pages name a canonical.
    context_links: bool = False
    # Product pages whose canonical points off-host (2.2 must ignore it).
    offhost_canonical: bool = False
    skus: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "skus", tuple(f"HT-{self.code}-{i:03d}" for i in range(1, self.products + 1))
        )


def _n(
    path: str,
    title: str,
    code: str,
    products: int = 0,
    *,
    children: tuple[Node, ...] = (),
    hidden_tiles: bool = False,
    context_links: bool = False,
    offhost_canonical: bool = False,
) -> Node:
    return Node(
        path=PREFIX + path,
        title=title,
        code=code,
        products=products,
        children=children,
        hidden_tiles=hidden_tiles,
        context_links=context_links,
        offhost_canonical=offhost_canonical,
    )


# The tree. Counts are chosen for their shapes, not their size: discs spans
# three pages, belts is the nest, finishing hides its tiles, blades links in
# category context, polish names an off-host canonical.
TREE: tuple[Node, ...] = (
    _n(
        "cutting/",
        "Cutting",
        "CUT",
        children=(
            _n("cutting/discs/", "Cutting discs", "CD", 25),
            _n("cutting/blades/", "Saw blades", "SB", 8, context_links=True),
        ),
    ),
    _n(
        "grinding/",
        "Grinding",
        "GRD",
        children=(
            _n("grinding/wheels/", "Grinding wheels", "GW", 12),
            _n(
                "grinding/belts/",
                "Belts",
                "BLT",
                children=(
                    _n("grinding/belts/narrow/", "Narrow belts", "BN", 5),
                    _n("grinding/belts/wide/", "Wide belts", "BW", 4),
                ),
            ),
        ),
    ),
    _n(
        "finishing/",
        "Finishing",
        "FIN",
        hidden_tiles=True,
        children=(
            _n("finishing/pads/", "Polishing pads", "PP", 7),
            _n("finishing/polish/", "Polishes", "PO", 3, offhost_canonical=True),
        ),
    ),
)


def _walk(nodes: tuple[Node, ...]) -> list[Node]:
    out: list[Node] = []
    for node in nodes:
        out.append(node)
        out.extend(_walk(node.children))
    return out


NODES: tuple[Node, ...] = tuple(_walk(TREE))
BY_PATH: dict[str, Node] = {n.path: n for n in NODES}
LEAVES: tuple[Node, ...] = tuple(n for n in NODES if n.products)
SKU_LEAF: dict[str, Node] = {sku: leaf for leaf in LEAVES for sku in leaf.skus}

# The exact product set: what a category seed must yield (phase-2 exit).
PRODUCTS: tuple[str, ...] = tuple(SKU_LEAF)
PRODUCT_URLS: tuple[str, ...] = tuple(f"{PREFIX}p/{sku}" for sku in PRODUCTS)

# Multi-select facets. Each link ADDS one value to the current query, so the
# reachable space is every subset of every dimension: 2^5 · 2^5 · 2^3 · 2^3
# per page of every leaf, far past spec 004 §3's 20,000-URL cap. A filter
# that changes nothing is the real-world shape, and is what makes a facet
# trap look like a working crawl.
FACETS: dict[str, tuple[str, ...]] = {
    "colour": ("red", "blue", "green", "black", "grey"),
    "grit": ("40", "60", "80", "120", "240"),
    "sort": ("price", "name", "new"),
    "per_page": ("10", "25", "50"),
}

# A chain of plain listing pages from the root, one tile each, for the depth
# cap (2.3): `/shop/deep/6/` is depth 6 from `/shop/`.
DEEP_PREFIX = f"{PREFIX}deep/"
DEEP_LEVELS = 8

# Unbounded traps of two more shapes (2.5); 1.4's `/trap/` is the third.
LOOP_PREFIX = f"{PREFIX}loop/"  # relative-link bug: …/loop/x/loop/x/…
NEWS_PREFIX = f"{PREFIX}news/"  # calendar: /shop/news/2026/10/ → next month

LONG_URL_LENGTH = 2100


def render(path: str, query: str, host: str) -> tuple[int, bytes] | None:
    """The page for `path?query`, or `None` if `path` is not under `/shop/`.

    A path with or without its trailing slash is the same page: `2.2` strips
    trailing slashes, and the canonical form has to be fetchable.
    """
    if path != PREFIX.rstrip("/") and not path.startswith(PREFIX):
        return None
    params = parse_qsl(query, keep_blank_values=True)
    slashed = path if path.endswith("/") else path + "/"

    if slashed == PREFIX:
        return 200, _root(host)
    if slashed.startswith(f"{PREFIX}p/"):
        return _product(slashed[len(PREFIX) + 2 :].strip("/"), host)
    if slashed.startswith(LOOP_PREFIX):
        return 200, _loop(slashed)
    if slashed.startswith(NEWS_PREFIX):
        return _news(slashed)
    if slashed.startswith(DEEP_PREFIX):
        return _deep(slashed)
    if "/p/" in slashed:
        # Category context: /shop/cutting/blades/p/HT-SB-001
        listing, _, sku = slashed.rpartition("/p/")
        leaf = BY_PATH.get(listing + "/")
        if leaf is not None and leaf.context_links:
            return _product(sku.strip("/"), host)
        return None
    node = BY_PATH.get(slashed)
    if node is None:
        return None
    return 200, _listing(node, params)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _fill(template: Path, **slots: str) -> bytes:
    html = template.read_text()
    for name, value in slots.items():
        html = html.replace("{{" + name + "}}", value)
    return html.encode()


def _a(href: str, text: str, cls: str = "", rel: str = "") -> str:
    attrs = f' class="{cls}"' if cls else ""
    attrs += f' rel="{rel}"' if rel else ""
    return f'<a{attrs} href="{escape(href)}">{escape(text)}</a>'


def _mega() -> str:
    """Every category node, on every page (spec 004 §3a's hazard)."""
    return "".join(_a(n.path, n.title, "mega__link") for n in NODES)


def _tiles(children: tuple[Node, ...], hidden: bool) -> str:
    """Scoped subcategory tiles: only this node's children."""
    style = ' style="display:none"' if hidden else ""
    links = "".join(_a(c.path, c.title, "subcategory-tile") for c in children)
    return f'<section class="subcategories"{style}>{links}</section>'


def _listing_page(title: str, **slots: str) -> bytes:
    defaults = {
        "canonical": "",
        "mega": _mega(),
        "tiles": "",
        "facets": "",
        "products": "",
        "pagination": "",
        "extra": "",
    }
    return _fill(LISTING, title=escape(title), **(defaults | slots))


def _root(host: str) -> bytes:
    archive = Node(path=f"{DEEP_PREFIX}1/", title="Archive 1", code="DEEP")
    return _listing_page(
        "All tools",
        tiles=_tiles((*TREE, archive), hidden=False),
        extra=_promo(host) + _rejects(),
    )


def _promo(host: str) -> str:
    """Canonicalisation material for 2.2: one listing, many spellings."""
    discs = f"{PREFIX}cutting/discs/"
    upper = host.upper()
    default_port = "" if ":" in host else ":80"
    spellings = [
        f"{discs}?utm_source=newsletter&utm_medium=email",
        f"{discs}?gclid=abc123",
        f"{discs}?ref=homepage",
        f"{discs}#top",
        f"{discs}?per_page=25&colour=red",
        f"{discs}?colour=red&per_page=25",
        f"{PREFIX}cutting/./discs/../discs/",
        f"{PREFIX}/cutting//discs/",
        f"{PREFIX}cutting/discs",
        f"http://{upper}{default_port}{discs}",
        f"{discs}?page=2",
    ]
    links = "".join(_a(href, "Cutting discs", "promo__link") for href in spellings)
    return f'<section class="promo">{links}</section>'


def _rejects() -> str:
    """Links discovery must refuse (2.3, 2.5)."""
    hrefs = [
        "https://elsewhere.test/shop/",
        f"https://cdn.{HOST}/shop/catalogue.pdf",
        f"mailto:sales@{HOST}",
        "tel:+441234567890",
        "javascript:void(0)",
        f"{PREFIX}search?q=" + "x" * LONG_URL_LENGTH,
        f"{NEWS_PREFIX}2026/10/",
        f"{LOOP_PREFIX}x/",
    ]
    links = "".join(_a(href, "more", "footer__link") for href in hrefs)
    return f'<footer class="site-footer">{links}</footer>'


def _listing(node: Node, params: list[tuple[str, str]]) -> bytes:
    if not node.products:
        return _listing_page(node.title, tiles=_tiles(node.children, node.hidden_tiles))

    page = _page_number(params)
    pages = max(1, -(-node.products // PER_PAGE))
    skus = node.skus[(page - 1) * PER_PAGE : page * PER_PAGE]
    base = node.path
    products = "".join(
        "<li>" + _a(_product_href(node, sku), sku, "product-card__link") + "</li>" for sku in skus
    )
    return _listing_page(
        node.title,
        facets=_facets(base, params),
        products=products,
        pagination=_pagination(base, params, page, pages),
    )


def _product_href(leaf: Node, sku: str) -> str:
    if leaf.context_links:
        return f"{leaf.path}p/{sku}"
    return f"{PREFIX}p/{sku}"


def _page_number(params: list[tuple[str, str]]) -> int:
    for key, value in params:
        if key == "page" and value.isdigit() and int(value) > 0:
            return int(value)
    return 1


def _with(params: list[tuple[str, str]], key: str, value: str) -> str:
    """`params` with `key` replaced (page) — the query string, not a URL."""
    kept = [(k, v) for k, v in params if k != key]
    return urlencode([*kept, (key, value)])


def _facets(base: str, params: list[tuple[str, str]]) -> str:
    """One link per facet value not yet selected, each ADDING it to the
    current query (page dropped, as real filters do)."""
    chosen = {(k, v) for k, v in params}
    kept = [(k, v) for k, v in params if k != "page"]
    links = []
    for key, values in FACETS.items():
        for value in values:
            if (key, value) in chosen:
                continue
            links.append(_a(f"{base}?{urlencode([*kept, (key, value)])}", value, "facet"))
    return "".join(links)


def _pagination(base: str, params: list[tuple[str, str]], page: int, pages: int) -> str:
    links = [
        _a(f"{base}?{_with(params, 'page', str(n))}", str(n), "pagination__page")
        for n in range(1, pages + 1)
        if n != page
    ]
    if page < pages:
        links.append(_a(f"{base}?{_with(params, 'page', str(page + 1))}", "Next", rel="next"))
    return "".join(links)


def _product(sku: str, host: str) -> tuple[int, bytes] | None:
    leaf = SKU_LEAF.get(sku)
    if leaf is None:
        return None
    n = int(sku.rsplit("-", 1)[1])
    if leaf.offhost_canonical:
        canonical = f"https://elsewhere.test/p/{sku}"
    elif leaf.context_links:
        canonical = f"{PREFIX}p/{sku}"
    else:
        canonical = ""
    crumbs = [_a(PREFIX, "Halden Tools")]
    crumbs += [_a(n_.path, n_.title) for n_ in NODES if leaf.path.startswith(n_.path)]
    body = _fill(
        PRODUCT,
        title=escape(f"{leaf.title} {n}"),
        canonical=f'<link rel="canonical" href="{escape(canonical)}" />' if canonical else "",
        mega=_mega(),
        breadcrumb="".join(crumbs),
        price=f"£{5 + n}.{(n * 7) % 100:02d}",
        sku=sku,
    )
    return 200, body


def _loop(path: str) -> bytes:
    """A relative-link bug: every page links `loop/x/` relative to itself, so
    the path grows by one `loop/x/` pair per hop, for ever."""
    depth = path.count("loop/x/")
    return _listing_page(f"Loop {depth}", tiles=_tiles_raw(["loop/x/"]))


def _news(path: str) -> tuple[int, bytes] | None:
    """A calendar trap: every month links the next one, without end."""
    parts = path[len(NEWS_PREFIX) :].strip("/").split("/")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    year, month = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12:
        return None
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    nxt = f"{NEWS_PREFIX}{ny}/{nm:02d}/"
    return 200, _listing_page(f"News {year}-{month:02d}", pagination=_a(nxt, "Next", rel="next"))


def _deep(path: str) -> tuple[int, bytes] | None:
    tail = path[len(DEEP_PREFIX) :].strip("/")
    if not tail.isdigit() or not 1 <= int(tail) <= DEEP_LEVELS:
        return None
    level = int(tail)
    children = (
        (Node(path=f"{DEEP_PREFIX}{level + 1}/", title=f"Archive {level + 1}", code="DEEP"),)
        if level < DEEP_LEVELS
        else ()
    )
    return 200, _listing_page(f"Archive {level}", tiles=_tiles(children, hidden=False))


def _tiles_raw(hrefs: list[str]) -> str:
    links = "".join(_a(h, h, "subcategory-tile") for h in hrefs)
    return f'<section class="subcategories">{links}</section>'
