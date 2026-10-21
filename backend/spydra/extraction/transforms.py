"""The transform table (spec 003 §2).

Small pure functions, composed in order. Two of them are where silent bad
data comes from, so they fail loudly instead:

- **`parse_decimal` fails on ambiguity.** `1,234` is 1234 in English and
  1.234 in German, and guessing turns a €1,234 part into a €1.234 one. When
  the shape does not determine the value, the transform returns `None` and
  validation records the failure — spec 003 §2: "fails loudly on ambiguity".
- **`strip_currency` keeps the sign and the decimal** and removes only the
  symbol and the thousands separators. A regex that stripped everything
  non-numeric would turn `-1.50` into `150`.

Nothing here raises. A transform that cannot produce a value returns `None`,
and `validation.py` is what records why — spec 003 §3's "validation never
raises, it records", applied one layer earlier.
"""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from spydra.domain.entities import FieldValue, Transform
from spydra.domain.enums import TransformName

_WHITESPACE = re.compile(r"\s+")

# Currency symbols and codes we strip before parsing. The symbol is also the
# first source of truth for *which* currency (spec 003 §2), so detection
# reads this table rather than guessing from the page.
CURRENCY_SYMBOLS: Mapping[str, str] = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "CHF": "CHF",
    "SEK": "SEK",
    "PLN": "PLN",
}

# A number with a thousands separator and no decimal part is ambiguous:
# `1,234` is 1234 to an English site and 1.234 to a German one. Spec 003 §2
# says parse_decimal "fails loudly on ambiguity", and this is the shape that
# triggers it.
_AMBIGUOUS = re.compile(r"^-?\d{1,3}([.,])\d{3}$")


def trim(value: str) -> str:
    """Collapse whitespace and strip. The default for `attr = "text"`."""
    return _WHITESPACE.sub(" ", value).strip()


def strip_currency(value: str) -> str:
    """Remove the symbol, the currency code and any **unambiguous** thousands
    separator; keep the sign and the decimal separator.

    Spec 003 §2 asks for "remove symbol and thousands separators, keep sign
    and decimal", and the word doing the work is *thousands*. Which separator
    is the thousands one is not always knowable:

    - `1,234.56` and `1.234,56` have two different separators, so the first
      of them is thousands and can go.
    - `24,90` has one, and it is a decimal comma.
    - `1,234` has one, and it is **ambiguous** — 1234 to an English site,
      1.234 to a German one. Stripping it here would silently pick the
      English reading, so it is left alone and `parse_decimal` refuses it.

    So this removes a separator only where the string itself settles the
    question, and the ambiguous case travels on intact to be rejected rather
    than guessed at. Keeping the sign matters for the same reason: a regex
    that dropped everything non-numeric would turn `-1.50` into `150`.
    """
    out = trim(value)
    for symbol, code in CURRENCY_SYMBOLS.items():
        out = out.replace(symbol, "").replace(code, "")
    out = out.replace("\xa0", "").replace(" ", "").strip()

    # Two different separators: the LAST one is the decimal, so the other is
    # thousands and is safe to remove.
    if "," in out and "." in out:
        decimal_sep = "," if out.rfind(",") > out.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        out = out.replace(thousands_sep, "")

    return out


def detect_currency(
    value: str, page_currency: str | None, domain_default: str | None
) -> str | None:
    """Symbol first, then the page's declared currency, then the domain
    default (spec 003 §2).

    Returns `None` rather than a guess when none of the three is available.
    A price without a determinable currency is a **validation failure**, not
    a `0.00` and not an assumed GBP — spec 003 §2 is explicit, and a wrong
    currency is worse than a missing one because it looks like data.
    """
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in value:
            return code
    return page_currency or domain_default


def parse_decimal(value: str) -> Decimal | None:
    """To `Decimal`, or `None` when the text does not determine a number.

    `None` on:
    - anything non-numeric (`POA`, `Call for price`, an empty string);
    - an **ambiguous** separator (`1,234`), per spec 003 §2.

    "POA" is the case spec 003 §5 calls out by name: it must be a validation
    failure rather than becoming `0.00`. A price of zero is a price, and a
    catalogue full of zeros looks like data.
    """
    text = strip_currency(value)
    if not text:
        return None
    if _AMBIGUOUS.match(text):
        return None

    # European decimal comma, unambiguous because there is no second
    # separator: `24,90` is 24.90.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    # Thousands separators around an explicit decimal point: `1,234.50`.
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def absolute_url(value: str, page_url: str) -> str:
    """Resolve against the page URL (spec 003 §2)."""
    return urljoin(page_url, trim(value))


def pairs(cells: Sequence[str]) -> Mapping[str, str]:
    """A spec table's cells to a key/value mapping for JSONB.

    Takes an already-flattened `[th, td, th, td, …]` sequence: the selector
    strategy resolves the two column selectors and interleaves them, because
    the pairing is a property of the DOM and this stays a pure function.
    An odd trailing cell is dropped rather than paired with nothing.
    """
    it = iter(cells)
    return {trim(k): trim(v) for k, v in zip(it, it, strict=False)}


def apply_chain(
    value: FieldValue,
    chain: Sequence[Transform],
    *,
    page_url: str,
) -> FieldValue:
    """Run the transforms in order.

    Order is the caller's; this does not reorder or dedupe. `first` and `all`
    are cardinality rather than value transforms, so they are applied by the
    strategy that knows whether the rule was `many` — see `selector.py`.
    """
    out = value
    for step in chain:
        out = _apply_one(out, step, page_url=page_url)
    return out


def _apply_one(value: FieldValue, step: Transform, *, page_url: str) -> FieldValue:
    if value is None:
        # A transform chain on a field that resolved to nothing stays
        # nothing. Running `parse_decimal` on None would be a crash in the
        # one path that is supposed to record rather than raise.
        return None

    if step.name is TransformName.TRIM:
        return trim(value) if isinstance(value, str) else value
    if step.name is TransformName.STRIP_CURRENCY:
        return strip_currency(value) if isinstance(value, str) else value
    if step.name is TransformName.PARSE_DECIMAL:
        return parse_decimal(value) if isinstance(value, str) else value
    if step.name is TransformName.ABSOLUTE_URL:
        if isinstance(value, str):
            return absolute_url(value, page_url)
        if isinstance(value, Sequence):
            return [absolute_url(v, page_url) for v in value if isinstance(v, str)]
        return value
    if step.name is TransformName.FIRST:
        if isinstance(value, Sequence) and not isinstance(value, str):
            return value[0] if value else None
        return value
    if step.name is TransformName.ALL:
        if isinstance(value, str):
            return [value]
        return value
    if step.name is TransformName.PAIRS:
        if isinstance(value, Sequence) and not isinstance(value, str):
            return pairs([v for v in value if isinstance(v, str)])
        return value
    return value
