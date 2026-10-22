"""`is_empty`: did one value resolve to anything at all?

The leaf both halves of "nothing usable" are built on. `hashing.normalise`
drops what this calls empty, and `validation.empty_extraction` is defined over
`hashing.is_substantive` (ADR-0037). It lives on its own because the predicate
now depends on the hasher, and the hasher already depended on this: kept in
`validation.py`, the two modules would import each other.
"""

from collections.abc import Mapping, Sequence


def is_empty(value: object) -> bool:
    """Did this field resolve to anything usable?

    Takes `object` rather than `FieldValue` so the normaliser can ask the
    same question about a nested item without a cast — a second emptiness
    test in the hasher is exactly the drift ADR-0027 names. An empty string,
    a whitespace-only string, an empty sequence and an empty mapping are all
    "nothing" — `0` and `Decimal("0")` are **not**, because a genuine zero is
    data.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value
    if isinstance(value, Sequence):
        return len(value) == 0
    return False


def is_blank(fields: Mapping[str, object]) -> bool:
    """No field resolved to anything, not even an asset URL.

    **Not a verdict on the page.** `empty_extraction` is the verdict. This is
    the chain's question of whether a rung left anything worth carrying: an
    image-only SEO stub is an empty extraction (nothing substantive), but its
    image URLs still belong in the asset queue, so the chain keeps it as a
    fallback instead of discarding it.
    """
    return all(is_empty(value) for value in fields.values())
