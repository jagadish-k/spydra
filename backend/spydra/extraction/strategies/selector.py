"""Rung 2 — the domain's approved template (spec 003 §2).

`selectolax`'s `LexborHTMLParser` for CSS selection: roughly an order of
magnitude faster than BeautifulSoup and sufficient for the job, with lxml
reserved for if XPath is ever genuinely needed (spec 003 §2).

**Nothing here routes or halts.** A selector that resolves to nothing yields
`None` for that field, validation records it, and the observation is written
with whatever else resolved (ADR-0027). The one thing that *is* control flow
is the whole-page case — every field empty on a 200 — and that lives in
`validation.empty_extraction` as a single predicate with three callers,
precisely so this strategy does not get an opinion about it.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from spydra.domain.entities import ExtractedFields, FieldRule, FieldValue, Template
from spydra.domain.enums import Strategy, TransformName
from spydra.domain.fetch import FetchedPage
from spydra.extraction.transforms import apply_chain, detect_currency, parse_decimal, trim


class SelectorStrategy:
    """`ExtractionStrategy` over a template's `FieldRule` map."""

    name = Strategy.SELECTOR

    def __init__(self, domain_currency: str | None = None) -> None:
        # Third and last source of truth for currency, after the symbol and
        # the page's own declaration (spec 003 §2).
        self._domain_currency = domain_currency

    async def extract(
        self, page: FetchedPage, template: Template | None = None
    ) -> ExtractedFields | None:
        """`None` when there is no template at all.

        Not an empty mapping: "no template" is `no_template` in
        `unknown_pages` — a configuration gap — and ADR-0027 §3 excludes
        those pages from the `broken` threshold's numerator entirely. An
        empty mapping here would make a domain with no template look like a
        domain that had been redesigned.
        """
        if template is None or not template.extraction:
            return None

        tree = LexborHTMLParser(page.body)
        page_currency = self._declared_currency(tree)

        fields: dict[str, FieldValue] = {}
        for name, rule in template.extraction.items():
            fields[name] = self._field(tree, rule, page)

        price = fields.get("price")
        if price is not None:
            # Price is the one field that carries two values, and spec 003 §2
            # makes the currency a first-class part of it: a price without a
            # determinable currency is a validation failure, so the amount
            # and the code travel together and `validation.currency` checks
            # both halves.
            fields["price"] = self._price(price, page_currency)

        return fields

    def _field(self, tree: LexborHTMLParser, rule: FieldRule, page: FetchedPage) -> FieldValue:
        nodes = tree.css(rule.selector)
        if not nodes and rule.fallback:
            nodes = tree.css(rule.fallback)

        values = [self._value(node, rule.attr) for node in nodes]
        present = [v for v in values if v is not None]

        raw: FieldValue
        if rule.many or any(t.name is TransformName.PAIRS for t in rule.transform):
            raw = present
        else:
            raw = present[0] if present else None

        return apply_chain(raw, rule.transform, page_url=page.final_url)

    @staticmethod
    def _value(node: LexborNode, attr: str) -> str | None:
        if attr == "text":
            text = node.text(deep=True)
            return trim(text) if text else None
        value = node.attributes.get(attr)
        return trim(value) if value else None

    def _price(
        self, value: FieldValue, page_currency: str | None
    ) -> Mapping[str, str | Decimal | None]:
        """`{amount, currency}`, with either half possibly missing.

        Missing rather than guessed. A price whose currency cannot be
        determined is recorded as a currency validation failure (spec 003
        §2/§3) — assuming the domain default when the page said nothing
        different would be the one error that looks exactly like data.
        """
        text = str(value)
        return {
            "amount": parse_decimal(text),
            "currency": detect_currency(text, page_currency, self._domain_currency),
            # The raw text, kept so a failure can say what it SAW. Spec 003
            # §3's example record is literally
            # `{"rule": "currency", "ok": false, "saw": "POA"}` — "POA" is
            # the thing that explains the failure to an operator, and a
            # record saying `{'amount': None, 'currency': 'GBP'}` explains
            # nothing. Without this the price is the one field whose failure
            # is unreadable, which is the field most likely to fail.
            "raw": text,
        }

    @staticmethod
    def _declared_currency(tree: LexborHTMLParser) -> str | None:
        """The page's own declaration, second in spec 003 §2's order.

        `itemprop="priceCurrency"` and the OpenGraph equivalent, because
        those are what a page that bothers to say actually uses.
        """
        for selector, attr in (
            ('[itemprop="priceCurrency"]', "content"),
            ('meta[property="product:price:currency"]', "content"),
            ('meta[property="og:price:currency"]', "content"),
        ):
            node = tree.css_first(selector)
            if node is None:
                continue
            value = node.attributes.get(attr)
            if value:
                return trim(value).upper()
        return None


def interleave(first: Sequence[str], second: Sequence[str]) -> list[str]:
    """Flatten two column selections into the sequence `pairs` expects.

    Here rather than in `transforms.py` because the pairing is a property of
    the DOM — two `css()` results — and `transforms.py` stays pure functions
    over values.
    """
    out: list[str] = []
    for key, value in zip(first, second, strict=False):
        out.extend((key, value))
    return out
