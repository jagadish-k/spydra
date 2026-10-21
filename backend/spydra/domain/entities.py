"""The entities. Frozen, slotted, no I/O (spec 001 §3).

Repositories translate rows to these and back; nothing here knows a row
exists. `tests/test_import_contracts.py` holds that line.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .enums import (
    DomainState,
    PageKind,
    ProposedBy,
    RenderMode,
    RuleName,
    Strategy,
    TransformName,
)
from .ids import DomainId, PageId, RunId, TemplateId

# A field's extracted value before it reaches a column or JSONB. `many` rules
# yield a sequence; `pairs` yields a mapping (spec 003 §2).
#
# `PriceValue` is the one composite, and it is composite because spec 003 §2
# makes the currency a first-class part of a price: "a price without a
# determinable currency is a validation failure, not a guess". Amount and
# code therefore have to travel together so one rule can check both, and
# `raw` travels with them so a failure can report what it SAW — spec 003 §3's
# example record is `{"rule": "currency", "ok": false, "saw": "POA"}`, and
# "POA" is the only part of that which explains anything.
#
# `1.11` splits it into `page_observations.price_amount` and `price_currency`
# (spec 001 §1). Widened here in BUILD_PLAN 1.10 rather than invented in an
# adapter, so both extraction rungs emit one shape.
PriceValue = Mapping[str, "str | Decimal | None"]
FieldValue = str | Decimal | int | Sequence[str] | Mapping[str, str] | PriceValue | None
ExtractedFields = Mapping[str, FieldValue]


@dataclass(frozen=True, slots=True)
class Transform:
    """One step of a transform chain (spec 003 §2).

    A dataclass rather than a bare enum member because `pairs(th, td)` takes
    arguments. Modelling six of the seven as enum members and the seventh as
    a special case is the shape that makes the chain grow an `if`; carrying
    args that are usually empty does not.
    """

    name: TransformName
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Rule:
    """One validation rule (spec 003 §3).

    `min_count(n)` and `matches(re)` take an argument; the rest do not.
    """

    name: RuleName
    arg: str | int | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """What a rule saw, recorded rather than raised.

    Spec 003 §3: validation never raises. It lands in
    `page_observations.validation` as {field: {rule, ok, saw}}, which is what
    makes a silently broken selector visible in a report instead of as quiet
    bad data.
    """

    rule: RuleName
    ok: bool
    saw: str | None = None


@dataclass(frozen=True, slots=True)
class FieldRule:
    """How one field is found and checked (spec 001 §3)."""

    selector: str
    attr: str = "text"  # 'text' | an attribute name
    many: bool = False
    # INERT (ADR-0027). Kept so prior template versions (ADR-0006) and the
    # templates.extraction JSONB keep their shape; nothing reads it, the YAML
    # loader rejects `required: true` rather than ignoring it (BUILD_PLAN
    # 1.12), and tests/domain/test_required_is_inert.py holds that line.
    required: bool = False
    transform: tuple[Transform, ...] = ()
    validation: tuple[Rule, ...] = ()
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRules:
    """How a listing page yields more URLs (`templates.discovery`, spec 001 §1).

    Empty is legitimate and common: a product template discovers nothing.
    """

    next_page: str | None = None
    product_links: str | None = None
    subcategory_links: str | None = None
    allow_patterns: tuple[str, ...] = ()
    deny_patterns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Domain:
    """A host and the politeness contract for it (spec 001 §3).

    `next_eligible_at` and `consecutive_failures` are carried here because the
    scheduler's whole question — may I fetch from this host now — is answered
    from them (ADR-0002). `in_flight` is deliberately absent: spec 001 §1
    calls it a cache that must be reconciled rather than trusted, so it stays
    in the row and out of the entity.
    """

    id: DomainId
    host: str
    state: DomainState
    render_mode: RenderMode
    crawl_delay_ms: int
    max_concurrency: int
    asset_concurrency: int
    respect_robots: bool
    next_eligible_at: datetime
    consecutive_failures: int
    user_agent: str | None = None
    max_depth: int = 5
    deny_patterns: tuple[str, ...] = ()

    @property
    def crawls(self) -> bool:
        """Spec 001 §2: a domain that is not ACTIVE sends no requests."""
        return self.state is DomainState.ACTIVE


@dataclass(frozen=True, slots=True)
class Template:
    """Extraction and discovery rules for one (domain, url_pattern) (ADR-0006).

    `url_pattern` is a compiled pattern, not a string: it is matched against
    every discovered URL, and compiling it at the repository boundary means an
    unusable regex fails when the template is read rather than mid-crawl.
    """

    id: TemplateId
    domain_id: DomainId
    name: str
    url_pattern: str
    page_kind: PageKind
    version: int
    is_active: bool
    discovery: DiscoveryRules
    extraction: Mapping[str, FieldRule]
    proposed_by: ProposedBy
    approved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """One crawl of one page. Append-only (ADR-0007, AGENTS.md rule 13).

    There is no `id` and no setter. An Observation is constructed, written
    once and never updated; a mutable one would make rule 13 a convention
    instead of a type.
    """

    page_id: PageId
    run_id: RunId
    template_id: TemplateId | None
    observed_at: datetime
    http_status: int
    # Optional because an observation can exist with no rung behind it:
    # a 200 from which nothing resolved is still an observation (it is
    # the one the `broken` threshold counts), and spec 001 §1 makes the
    # column nullable for exactly that row.
    strategy: Strategy | None
    content_hash: bytes
    fields: ExtractedFields
    validation: Mapping[str, ValidationResult] = field(default_factory=dict)
    unchanged: bool = False
    # ADR-0027's verdict, COMPUTED ONCE and carried to the row (1.11).
    # The `broken` threshold is a query, and a query that re-derived
    # emptiness from the columns would be a fourth definition of
    # `empty_extraction` — the one most able to disagree, since
    # `attributes = '{}'` is not the question `all(is_empty(v))` asks.
    empty_extraction: bool = False
    # Which rung produced the fields, when `strategy` is spending itself
    # on spec 012 §4's `static_fallback` instead. See
    # `.tasks/feat-1.11-observation-writes.md` open question 1: one
    # column cannot answer both questions and three documents name
    # `strategy = static_fallback`, so both facts are recorded.
    extraction_rung: Strategy | None = None

    @property
    def failed_validation(self) -> frozenset[str]:
        """Fields whose validation did not pass.

        **Evidence, not control flow** (ADR-0027). No field is required, so a
        failure here never routes the page to `unknown_pages` and never halts
        the domain — it is recorded for the operator to read. The routing
        signal is emptiness: a 200 from which nothing resolved at all.
        """
        return frozenset(n for n, v in self.validation.items() if not v.ok)
