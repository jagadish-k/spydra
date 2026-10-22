"""Validation, and the one predicate three things depend on (spec 003 §3).

**Validation records; it never raises and it never routes** (ADR-0027). A
failing field is written into `page_observations.validation` as evidence for
the operator, the observation is written with whatever did resolve, and
partial data is never discarded. Nothing is `required`, so a per-field
failure is not control flow.

**`empty_extraction` is one function with three callers**, and that is a
stated requirement rather than a style preference (spec 003 §3, ADR-0027):

1. the `auto` render-mode fallback (spec 012 §4) — evaluated on the
   **static attempt**;
2. the `unknown_pages` reason;
3. the `broken` threshold — both evaluated on the **final** observation,
   after any `auto` fallback has run.

All three call this function and nothing else. 1.13 briefly gave the first
caller its own test ("not substantive"), which made two definitions of
"nothing usable" in production; ADR-0037 folded that test into the predicate
so the three agree again.

ADR-0027 pins where each is evaluated, and the reason is concrete: without
(3) a domain whose grid needs rendering would score empty on essentially
every page, cross 20% and move itself to `broken` on its first run while the
render path was working perfectly. Three copies of this predicate would
disagree about what "nothing came back" means, and the disagreement would
show up as a healthy domain stopping itself.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse

from spydra.domain.entities import ExtractedFields, FieldRule, FieldValue, Rule, ValidationResult
from spydra.domain.enums import RuleName
from spydra.extraction.emptiness import is_empty
from spydra.extraction.hashing import is_substantive

# ISO-4217 is three letters. A two- or four-letter "currency" is a parsing
# accident rather than a currency.
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


def empty_extraction(http_status: int, fields: ExtractedFields) -> bool:
    """ADR-0027's predicate as ADR-0037 restates it: a 200 response from
    which nothing **substantive** was extracted.

    "Substantive" is `hashing.is_substantive`: something survives the content
    hash's normalisation. Asset URLs do not, so a page whose only field is an
    image URL is an empty extraction. That is the SEO plugin's image-only
    `Product` stub over a redesigned page, which must reach the inbox and
    count toward the threshold rather than read as a page that worked.

    **The status is part of it.** A 404 that yielded nothing is not an empty
    extraction — it is a 404, and counting it would make every dead link
    evidence of a redesign. ADR-0030 then excludes pages with no prior
    observation from the `broken` threshold for the same reason from the
    other direction.
    """
    if http_status != 200:
        return False
    return not is_substantive(fields)


def validate_field(value: FieldValue, rules: Sequence[Rule]) -> ValidationResult | None:
    """Check one field. Returns the **first failure**, or None if all passed.

    First failure rather than all of them: `page_observations.validation`
    stores one result per field (spec 003 §3's `{field: {rule, ok, saw}}`),
    and the first failing rule is the one that explains the field.
    """
    for rule in rules:
        if not _passes(value, rule):
            return ValidationResult(rule=rule.name, ok=False, saw=_saw(value))
    return None


def validate(
    fields: ExtractedFields, rules: Mapping[str, FieldRule]
) -> Mapping[str, ValidationResult]:
    """Every field, every rule. Records failures only.

    Only failures are recorded because `validation` is evidence: a map
    containing every field that passed would bury the one that did not, and
    the operator reads this to find a broken selector.
    """
    results: dict[str, ValidationResult] = {}
    for name, rule in rules.items():
        failure = validate_field(fields.get(name), rule.validation)
        if failure is not None:
            results[name] = failure
    return results


def _passes(value: FieldValue, rule: Rule) -> bool:
    if rule.name is RuleName.NON_EMPTY:
        return not is_empty(value)

    if rule.name is RuleName.CURRENCY:
        # Spec 003 §3: "parses to a Decimal and has a 3-letter currency".
        # Both halves — a price of "POA" fails the first, and a price whose
        # currency could not be determined fails the second. Neither becomes
        # 0.00 and neither becomes an assumed GBP.
        if isinstance(value, Mapping):
            amount = value.get("amount")
            code = value.get("currency")
            return _is_decimal(amount) and bool(code) and bool(_CURRENCY_CODE.match(str(code)))
        return _is_decimal(value)

    if rule.name is RuleName.URL:
        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    if rule.name is RuleName.INTEGER:
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        if isinstance(value, str):
            return value.strip().lstrip("-").isdigit()
        return False

    if rule.name is RuleName.DATE:
        # ISO-8601 text only. An earlier version also accepted `datetime` and
        # `date` objects, which is dead code: `FieldValue` cannot hold one
        # (spec 001 §3) and no transform in spec 003 §2's table produces one,
        # so the branch could never be taken. mypy found it when a test tried
        # to exercise it.
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.strip())
        except ValueError:
            return False
        return True

    if rule.name is RuleName.MIN_COUNT:
        wanted = int(rule.arg) if rule.arg is not None else 1
        if isinstance(value, str) or value is None:
            return False
        if isinstance(value, Mapping | Sequence):
            return len(value) >= wanted
        return False

    if rule.name is RuleName.MATCHES:
        if not isinstance(value, str) or rule.arg is None:
            return False
        return re.search(str(rule.arg), value) is not None

    return True


def _is_decimal(value: object) -> bool:
    return isinstance(value, Decimal | int) and not isinstance(value, bool)


def _saw(value: FieldValue) -> str | None:
    """What the operator needs in order to recognise the problem.

    Spec 003 §3's example is `{"rule": "currency", "ok": false, "saw": "POA"}`
    — the **raw text**, which is the thing that explains the failure.

    A composite value (the price, which carries an amount and a currency)
    therefore reports its `raw` rather than its own repr: a record reading
    `{'amount': None, 'currency': 'GBP'}` says only that something went
    wrong, while `POA` says what. Truncated, because a whole product
    description in a validation record is noise.
    """
    if value is None:
        return None
    if isinstance(value, Mapping) and "raw" in value:
        text = str(value["raw"])
    else:
        text = str(value)
    return text if len(text) <= 120 else text[:117] + "..."
