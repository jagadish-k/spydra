"""`content_hash`, over the normalised extracted fields (spec 003 §4).

**Never over the markup.** Spec 003 §4's reason is concrete: raw HTML carries
timestamps, session tokens and CSRF fields, so hashing it marks every page
changed on every run and the "what changed" report becomes the catalogue.

Normalisation is that section's list, implemented literally:

| Spec 003 §4            | Here                                              |
| ---------------------- | ------------------------------------------------- |
| sorted keys            | `json.dumps(..., sort_keys=True)`                 |
| decimals canonicalised | `format(d.normalize(), "f")`                      |
| whitespace collapsed   | `" ".join(text.split())`                          |
| asset URLs excluded    | `is_asset_url`, by value — see below              |

**`format(d.normalize(), "f")` and not `str(d)`.** `normalize()` alone turns
`Decimal("100")` into `Decimal("1E+2")`, so two spellings of one price would
hash differently in the one direction that matters — a price that did not
move reported as a change. The `f` presentation type is what keeps the
exponent out.

**Empty values are dropped, using `is_empty`** — the same function
`empty_extraction` is built on (ADR-0027: one definition). A field that
resolved to nothing is nothing, and without this, adding a field to a
template that happens to match on no page changes the hash of every page in
the domain and reports the whole catalogue as redesigned.

**The price composite's `raw` is dropped.** `raw` exists for validation
evidence — spec 003 §3's `{"rule": "currency", "ok": false, "saw": "POA"}` —
and it is the pre-transform text. Hashing it makes a markup change from
`£10.50` to `GBP 10.50` a content change on a page whose price is identical,
which is the churn this whole section exists to avoid. It is dropped only
from a mapping that looks like a price (one that carries `amount` or
`currency`), so a `pairs` transform whose spec table genuinely has a "raw"
row keeps it.

**Asset URLs are excluded by value, not by field name.** Spec 003 §4 excludes
them "(they are hashed separately by content)", and the reason is the same one
that rules out hashing the markup: a CDN cache-buster or a re-upload changes
the URL of a byte-identical image, and a page whose photo was re-uploaded is
not a page whose content changed. The `1.4` fixture template defines an
`images` field today (`.gallery__image[src]`, many), so this is a live
concern and not a phase-4 one.

The filter is "a value that normalises to an absolute http(s) URL", because
the alternative — a hardcoded list of field names (`images`, `image_urls`,
`thumbnail`) — would invent the vocabulary `field_vocabulary` is meant to
define in phase 4, and would miss the fifth name a template picks. **Its
cost, stated:** a URL-valued field that is genuinely data (a link to a
manufacturer's page) cannot contribute to change detection either. That is
spec 003 §4's own trade, made where it can be seen; asset change is detected
by content in `observation_assets` (spec 008, `5.2`), which is what "hashed
separately by content" means.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from spydra.domain.entities import ExtractedFields
from spydra.extraction.assets import is_asset_url
from spydra.extraction.validation import is_empty

# A mapping carrying either of these is the price composite (spec 003 §2),
# which is the only shape whose `raw` is evidence rather than data.
_PRICE_KEYS: Final[frozenset[str]] = frozenset({"amount", "currency"})

_EVIDENCE_KEY: Final[str] = "raw"

type Normalised = str | list["Normalised"] | dict[str, "Normalised"]


def normalise(fields: ExtractedFields) -> dict[str, Normalised]:
    """Spec 003 §4's normalised form of an extraction.

    Returned rather than inlined into the hash so a test can assert on the
    thing that gets hashed. A hash is a 32-byte blob; a test that can only
    compare two blobs tells you *that* they differ and never *why*.
    """
    out: dict[str, Normalised] = {}
    for name, value in fields.items():
        if is_empty(value):
            continue
        normalised = _value(value)
        if normalised is None:
            continue
        out[name] = normalised
    return out


def is_substantive(fields: ExtractedFields) -> bool:
    """Does anything survive normalisation, i.e. is there content to compare?

    Not the same question as `empty_extraction`, and the difference is the
    asset URLs. A page whose only field is an image URL is **not** empty
    (ADR-0027: a field resolved), but nothing of it survives the hash, so it
    is not *substantive*: there is no content against which "unchanged" could
    mean anything. The chain uses this to keep looking for a better rung, and
    `content_hash` to refuse a hash of nothing. Defined over `normalise`, so
    the two cannot disagree about what counts.
    """
    return bool(normalise(fields))


def content_hash(fields: ExtractedFields) -> bytes | None:
    """sha256 over the canonical JSON of `normalise(fields)`, or `None` when
    nothing survives normalisation.

    **`None`, not the hash of `{}`.** Every page with nothing comparable
    would otherwise share one digest, and the writer reads equal digests as
    `unchanged`: an image-only page, or a page from which nothing resolved,
    would be recorded as "same as last time" for ever. Two NULLs are not
    equal in SQL either, which is the semantics wanted.

    32 raw bytes, for `page_observations.content_hash` (BYTEA). Not hex: the
    column is binary, and a hex string in a BYTEA column is a 64-byte value
    that compares equal to nothing anyone expects.
    """
    normalised = normalise(fields)
    if not normalised:
        return None
    # Keys sorted, no spaces, unicode left as unicode so a German product
    # name hashes as itself rather than as escapes.
    canonical = json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _value(value: object) -> Normalised | None:
    """One field, normalised. `None` means "nothing left after dropping".

    Order of the isinstance checks is load-bearing twice over: `bool` before
    `int` (`isinstance(True, int)` is `True`, and `Decimal(True)` is `1`,
    which would hash a flag as a price), and `str` before `Sequence` (a string
    is a sequence of strings, so the generic branch would recurse into
    characters).
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal | int):
        return _number(value)
    if isinstance(value, str):
        text = _text(value)
        return None if is_asset_url(text) else text
    if isinstance(value, Mapping):
        return _mapping(value)
    if isinstance(value, Sequence):
        return _sequence(value)
    # Nothing else can reach here: FieldValue (spec 001 §3) has no other
    # member. Normalised to its text rather than raising, because a hash that
    # raises mid-crawl loses an observation that was otherwise good.
    return _text(str(value))


def _number(value: Decimal | int) -> str:
    """One spelling per value. `10.50`, `10.5` and `1.05E+1` are one hash.

    `int` goes through `Decimal` as well, so a count extracted as `5` by one
    rung and `Decimal("5")` by the other does not change the hash — the two
    rungs are allowed to differ in type and not in meaning.
    """
    return format(Decimal(value).normalize(), "f")


def _text(value: str) -> str:
    """Whitespace collapsed (spec 003 §4): a reflowed template is not news."""
    return " ".join(value.split())


def _mapping(value: Mapping[object, object]) -> dict[str, Normalised] | None:
    is_price = bool(_PRICE_KEYS & {str(k) for k in value})
    out: dict[str, Normalised] = {}
    for key, item in value.items():
        name = _text(str(key))
        if is_price and name == _EVIDENCE_KEY:
            continue
        if is_empty(item):
            continue
        normalised = _value(item)
        if normalised is None:
            continue
        out[name] = normalised
    return out or None


def _sequence(value: Sequence[object]) -> list[Normalised] | None:
    """Order is preserved, because order is data.

    `category_path` is a path and a gallery is ordered; sorting them here
    would hide a re-ordered breadcrumb, which is a real site change.
    """
    out: list[Normalised] = []
    for item in value:
        if is_empty(item):
            continue
        normalised = _value(item)
        if normalised is None:
            continue
        out.append(normalised)
    return out or None
