"""Closed vocabularies shared by the schema, the API and the UI.

`StrEnum`, so a member serialises as the exact string the database enum and
the generated TypeScript both use. Where a value also appears in
`docs/specs/001-domain-model.md` §1 it is spelled identically on purpose —
`tests/domain/test_state_parity.py` holds that to the documentation.
"""

from enum import StrEnum, unique


@unique
class DomainState(StrEnum):
    """`crawl.domain_state`. Only ACTIVE sends requests (spec 001 §2)."""

    DISCOVERED = "discovered"
    AWAITING_APPROVAL = "awaiting_approval"
    ACTIVE = "active"
    PAUSED = "paused"
    BROKEN = "broken"
    ARCHIVED = "archived"


@unique
class DomainEvent(StrEnum):
    """What happened, not what state to move to.

    The lifecycle is keyed on (state, event) rather than on legal state pairs
    because two different events share one edge: an operator pausing a domain
    and three consecutive 403s pausing it (ADR-0004) both go
    ACTIVE → PAUSED, and the run report has to tell them apart. The event is
    also the thing the caller actually holds.
    """

    PROPOSE = "propose"
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"  # operator
    BLOCK = "block"  # three consecutive 403s — ADR-0004
    RESUME = "resume"
    BREAK = "break"  # validation failures over threshold — spec 003 §3
    RE_REVIEW = "re_review"
    ARCHIVE = "archive"


@unique
class RunState(StrEnum):
    """`crawl.run_state`."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@unique
class RenderMode(StrEnum):
    """How a domain is fetched.

    AUTO fetches statically and retries through the browser once if the
    template's required fields fail to resolve on a 200 (spec 001 §3), so a
    wrong guess at onboarding costs one cheap fetch rather than a silently
    empty extraction.
    """

    STATIC = "static"
    RENDERED = "rendered"
    AUTO = "auto"


@unique
class FetchPath(StrEnum):
    """Which adapter actually served a fetch.

    Recorded on every FetchedPage so an AUTO domain's fallback is observable
    rather than inferred. The scheduler neither knows nor cares which value
    this holds (ADR-0003 §gate); the run report does.
    """

    STATIC = "static"
    RENDERED = "rendered"


@unique
class PageKind(StrEnum):
    LISTING = "listing"
    PRODUCT = "product"


@unique
class ProposedBy(StrEnum):
    HUMAN = "human"
    LLM = "llm"


@unique
class Strategy(StrEnum):
    """Which rung of the extraction chain produced an observation (spec 003 §1)."""

    STRUCTURED = "structured"
    SELECTOR = "selector"
    LLM = "llm"


@unique
class TransformName(StrEnum):
    """Spec 003 §2. PAIRS is the one that takes arguments."""

    TRIM = "trim"
    STRIP_CURRENCY = "strip_currency"
    PARSE_DECIMAL = "parse_decimal"
    ABSOLUTE_URL = "absolute_url"
    FIRST = "first"
    ALL = "all"
    PAIRS = "pairs"


@unique
class RuleName(StrEnum):
    """Spec 003 §3. MIN_COUNT and MATCHES take an argument."""

    NON_EMPTY = "non_empty"
    CURRENCY = "currency"
    URL = "url"
    INTEGER = "integer"
    DATE = "date"
    MIN_COUNT = "min_count"
    MATCHES = "matches"


@unique
class UnknownReason(StrEnum):
    """Why a page landed in the review inbox (spec 001 §1, spec 003 §3)."""

    NO_TEMPLATE = "no_template"
    VALIDATION_FAILED = "validation_failed"
    EMPTY_EXTRACTION = "empty_extraction"
