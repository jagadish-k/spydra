"""Rung 1 — `schema.org/Product` from JSON-LD, microdata and RDFa (spec 003 §1).

**Cheapest first, and it needs no template.** Where a site emits structured
data it is more stable than CSS selectors, survives redesigns and needs no
model. Coverage on bespoke supplier catalogues will be low — JSON-LD is a
consumer-SEO feature — but it is free to try, and a page that has it should
never fall through to a selector that can break.

`extruct` does the parsing, per spec 003 §1's "do not hand-roll JSON-LD
parsing". The only judgement here is **which** of the embedded objects is the
product and how its offer maps onto our fields.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import extruct

from spydra.domain.entities import ExtractedFields, Template
from spydra.domain.enums import Strategy
from spydra.domain.fetch import FetchedPage
from spydra.extraction.hashing import is_substantive
from spydra.extraction.transforms import absolute_url, parse_decimal
from spydra.extraction.validation import is_empty

# schema.org/Product, however the page spells the @type.
_PRODUCT_TYPES = {
    "product",
    "schema:product",
    "https://schema.org/product",
    "http://schema.org/product",
}


class StructuredStrategy:
    """`ExtractionStrategy` over embedded structured data.

    Takes no template and ignores the one it is passed — that is the point of
    rung 1 (spec 003 §5: "a page with valid JSON-LD extracts via `structured`
    **without consulting a template**").
    """

    name = Strategy.STRUCTURED

    async def extract(
        self, page: FetchedPage, template: Template | None = None
    ) -> ExtractedFields | None:
        """The product's fields, or `None` so the chain moves to rung 2.

        `None` rather than an empty mapping, and the distinction matters: an
        empty mapping is "this rung ran and the page has nothing", which
        would stop the chain and make a selector template unreachable on
        every page that lacks JSON-LD.
        """
        product = self._find_product(page.body)
        if product is None:
            return None

        offers = self._first_offer(product)
        amount = parse_decimal(str(offers.get("price", ""))) if offers else None
        currency = str(offers.get("priceCurrency", "")) or None

        fields: dict[str, Any] = {
            "title": _text(product.get("name")),
            "sku": _text(product.get("sku")),
            "description": _text(product.get("description")),
            "vendor": _brand(product.get("brand")),
            "availability": _availability(offers.get("availability") if offers else None),
            "images": [absolute_url(u, page.final_url) for u in _urls(product.get("image"))],
        }
        if offers:
            # The SAME composite the selector rung emits. Two rungs emitting
            # two shapes for one field would make `1.11` handle both and let
            # the currency rule check only one of them — and the currency is
            # the half most likely to be missing.
            #
            # `currency` is whatever the page said and nothing more: an absent
            # `priceCurrency` is a missing currency, which spec 003 §2 makes a
            # validation failure rather than an assumption. The alternative is
            # a catalogue of plausible prices in the wrong currency, which
            # looks exactly like data.
            fields["price"] = {
                "amount": amount,
                "currency": currency,
                "raw": str(offers.get("price", "")),
            }

        # An all-empty composite is not a price, so it goes too — otherwise a
        # hollow `offers: {}` would make the page look extracted. "Hollow" is
        # the hasher's rule, not a third one: `raw` is evidence of what the
        # page said, not a value, so a composite carrying only `raw` has
        # nothing in it (ADR-0027 asks for one notion of empty).
        price = fields.get("price")
        if price is not None and not is_substantive({"price": price}):
            fields.pop("price", None)
        return {k: v for k, v in fields.items() if not is_empty(v)}

    def _find_product(self, html: str) -> Mapping[str, Any] | None:
        data = extruct.extract(html, syntaxes=["json-ld", "microdata", "rdfa"], uniform=True)
        for syntax in ("json-ld", "microdata", "rdfa"):
            for item in data.get(syntax, []):
                found = self._as_product(item)
                if found is not None:
                    return found
        return None

    def _as_product(self, item: Any) -> Mapping[str, Any] | None:
        """One object, or the first Product inside an `@graph`.

        Sites wrap their markup in a graph as often as not, and a reader that
        only looked at the top level would fall through to rung 2 on pages
        that have perfectly good structured data.
        """
        if not isinstance(item, Mapping):
            return None
        types = item.get("@type")
        names = {
            str(t).strip().lower() for t in (types if isinstance(types, list) else [types]) if t
        }
        if names & _PRODUCT_TYPES:
            return item
        graph = item.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                found = self._as_product(node)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _first_offer(product: Mapping[str, Any]) -> Mapping[str, Any]:
        offers = product.get("offers")
        if isinstance(offers, Mapping):
            return offers
        if isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, Mapping):
                    return offer
        return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        # `uniform=True` renders some nested values as objects with @value.
        inner = value.get("@value") or value.get("name")
        return str(inner) if inner else None
    if isinstance(value, list):
        return _text(value[0]) if value else None
    text = str(value).strip()
    return text or None


def _brand(value: Any) -> str | None:
    return _text(value)


def _availability(value: Any) -> str | None:
    """`https://schema.org/InStock` to `InStock`.

    The bare token, not the URL: `page_observations.availability` is TEXT
    that an operator reads, and a column of schema.org URLs is a column
    nobody can scan.
    """
    text = _text(value)
    if text is None:
        return None
    return text.rsplit("/", 1)[-1] or None


def _urls(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = _text(item)
            if text:
                out.append(text)
        return out
    text = _text(value)
    return [text] if text else []
