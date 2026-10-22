"""Spec 004 §2 step 7: the page's own answer to "what is my URL".

Honoured only on the same scheme and host. A canonical pointing elsewhere is
a syndication or a misconfigured template, and following it would file one
site's page under another's identity, or crawl off-host by the back door.
"""

from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from spydra.domain.urls import canonical_url


def canonical_link(html: str, page_url: str) -> str | None:
    """The canonical URL `html` names for itself, or `None`.

    The first `<link rel="canonical">` with an `href`, resolved against
    `page_url` and canonicalised. `None` when there is none, when it is
    empty or unparseable, or when its scheme and host differ from the
    page's. `page_url` is the URL the body was served from, after redirects:
    a relative canonical resolves against that.
    """
    if not html:
        return None
    for node in LexborHTMLParser(html).css("link[rel][href]"):
        rels = (node.attributes.get("rel") or "").lower().split()
        if "canonical" not in rels:
            continue
        href = (node.attributes.get("href") or "").strip()
        if not href:
            return None
        try:
            target = canonical_url(urljoin(page_url, href))
            page = urlsplit(canonical_url(page_url))
        except ValueError:
            # A supplier's own markup, so anything is possible: a templating
            # bug (`https://[object Object]/p`), a port typo. Unparseable is
            # "no canonical", never a crash of the page's crawl.
            return None
        resolved = urlsplit(target)
        if (resolved.scheme, resolved.netloc) != (page.scheme, page.netloc):
            return None
        return target
    return None
