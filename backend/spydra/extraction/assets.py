"""Which extracted values are asset URLs (spec 003 §4, spec 008 §1).

**One definition, two callers**, and the pairing is the reason this module
exists rather than a helper inside either of them:

1. `content_hash` **excludes** asset URLs, because a CDN cache-buster or a
   re-upload changes the URL of a byte-identical image and a page whose photo
   was re-uploaded is not a page whose content changed (spec 003 §4);
2. the asset enqueue (`1.12`) **picks them up**, because they are what spec
   008 §1's step 1 inserts into `asset_queue`.

Those two have to agree exactly. A URL excluded from the hash but not
enqueued is an image invisible to both change detection and the asset
pipeline — a value that fell between two definitions of one idea, which is
the failure ADR-0027 wrote down for the emptiness predicate and is no
different here.

**Matched on the value, not on the field name.** A template calls its image
field whatever it likes: `1.4`'s calls it `images`, and a hardcoded list of
names (`images`, `image_urls`, `thumbnail`) would miss the fifth name someone
picks. `field_vocabulary`, where a field could declare what it is, is phase 4
(spec 001 §4). **Cost, stated:** a URL-valued field that is genuinely a link
— a manufacturer's page — is treated as an asset by both callers. For the
hash that means it cannot contribute to change detection; for the enqueue it
means one fetch that spec 008 §2's content-type allowlist rejects on the
bytes. One wasted fetch per page, not bad data.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from spydra.domain.entities import ExtractedFields

# An asset URL is absolute. The `absolute_url` transform (spec 003 §2) is what
# makes it so, and a bare `/img/a.jpg` in a field that skipped that transform
# is as likely to be a product code as an image — guessing would put junk in
# `asset_queue` and drop a real field out of the hash.
_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")


def is_asset_url(value: object) -> bool:
    """Spec 003 §4's "asset URL", for one already-normalised value.

    Lowercased before the comparison: an `absolute_url` transform will
    happily produce `HTTPS://cdn...` from a page that shouts its scheme, and
    a hash that excluded one spelling and not the other would report a
    re-upload as a change on exactly those pages.
    """
    return isinstance(value, str) and value.strip().lower().startswith(_SCHEMES)


def asset_urls(fields: ExtractedFields) -> tuple[str, ...]:
    """Every asset URL an extraction produced, in order, deduplicated.

    **Order is `position` in `observation_assets`** (spec 001 §1), so a
    gallery keeps the order the page gave it. Deduplicated first-wins rather
    than last: a page that lists its hero image twice should keep it at
    position 0, and `UNIQUE (observation_id, source_url)` means the second
    copy has nowhere to go anyway.

    Nested values are walked, because a `pairs` transform can carry a URL and
    a `many` rule always produces a sequence of them.
    """
    found: list[str] = []
    seen: set[str] = set()
    for value in fields.values():
        for url in _walk(value):
            if url not in seen:
                seen.add(url)
                found.append(url)
    return tuple(found)


def _walk(value: object) -> list[str]:
    # `str` first, and before the generic `Sequence` branch: a string is a
    # sequence of strings, so the generic branch would recurse into
    # characters and find nothing, slowly.
    if isinstance(value, str):
        return [value.strip()] if is_asset_url(value) else []
    if isinstance(value, Mapping):
        return [url for item in value.values() for url in _walk(item)]
    if isinstance(value, Sequence):
        return [url for item in value for url in _walk(item)]
    return []
