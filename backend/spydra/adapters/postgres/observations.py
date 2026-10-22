"""Observation writes and the regression counts behind them (BUILD_PLAN 1.11).

Append-only (ADR-0007): there is one `INSERT` here and no `UPDATE` of a
`page_observations` row anywhere in the project. `page_current` is a view, so
"current state" needs no write at all — which is the property that makes the
`broken` threshold answerable, because the history it joins against is still
there.

**Not a port.** ADR-0008 puts ports at four boundaries and says repositories
for pages, templates and runs are ordinary code with no interface; this is
one of those. The consequence is deliberate: the orchestration in
`observations/writer.py` is proven against real Postgres rather than against
a hand-written double, which is also what TESTING.md §1 asks for — the
queries here are the part most able to be subtly wrong.

The SQL is written as SQL (AGENTS.md § Conventions, ADR-0014). The two
counting queries *are* ADR-0030, and a reader has to be able to check them
against it in one piece.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.domain.entities import FieldValue, Observation
from spydra.domain.enums import DomainState, UnknownReason
from spydra.domain.health import RunHealth
from spydra.domain.ids import DomainId, ObservationId, PageId, RunId

# Spec 001 §1's typed core columns. Everything else an extraction produced
# goes to `attributes` — the split is a row concern and lives here rather
# than in the extraction chain, which has no business knowing which fields
# got a column.
_CORE_TEXT: Final[tuple[str, ...]] = (
    "title",
    "availability",
    "vendor",
    "description",
)


@dataclass(frozen=True, slots=True)
class PriorObservation:
    """What the previous observation of a page says about this one.

    `empty_extraction` is carried because a lightweight `unchanged` row has
    no fields of its own, and recomputing the predicate against an empty
    mapping says `True` for every stable page on a stable site — which would
    report an unchanging catalogue as a redesign. The verdict is inherited
    with the hash it matched.
    """

    id: ObservationId
    content_hash: bytes | None
    empty_extraction: bool


_INSERT = sa.text(
    """
INSERT INTO crawl.page_observations
    (page_id, run_id, template_id, observed_at, http_status, content_hash,
     strategy, extraction_rung, unchanged, empty_extraction,
     title, price_amount, price_currency, availability, vendor,
     category_path, description, attributes, supplier, validation)
VALUES
    (:page_id, :run_id, :template_id, :observed_at, :http_status, :content_hash,
     :strategy, :extraction_rung, :unchanged, :empty_extraction,
     :title, :price_amount, :price_currency, :availability, :vendor,
     :category_path, :description,
     CAST(:attributes AS jsonb), CAST(:supplier AS jsonb),
     CAST(:validation AS jsonb))
RETURNING id
"""
)

_LATEST = sa.text(
    """
SELECT id, content_hash, empty_extraction
FROM crawl.page_observations
WHERE page_id = :page_id
ORDER BY observed_at DESC, id DESC
LIMIT 1
"""
)

# ADR-0030's numerator and denominator, in one pass over one run.
#
#   pages_crawled  distinct pages this run observed for this domain
#   regressions    of those, the ones whose LATEST observation in this run is
#                  empty AND which have an EARLIER non-empty observation
#   empty_pages    of those, the ones whose latest is empty, prior or not
#
# `DISTINCT ON (page_id) ... ORDER BY observed_at DESC` is why this is a
# subquery rather than a FILTER over the table: ADR-0027 pins the predicate
# to the FINAL observation of a page, after any `auto` fallback, and a page
# fetched twice in one run otherwise contributes its first attempt as well.
_HEALTH = sa.text(
    """
WITH final AS (
    SELECT DISTINCT ON (o.page_id)
           o.page_id, o.observed_at, o.empty_extraction
    FROM crawl.page_observations o
    JOIN crawl.pages p ON p.id = o.page_id
    WHERE o.run_id = :run_id
      AND p.domain_id = :domain_id
    ORDER BY o.page_id, o.observed_at DESC, o.id DESC
)
SELECT
    count(*) AS pages_crawled,
    count(*) FILTER (WHERE f.empty_extraction) AS empty_pages,
    count(*) FILTER (
        WHERE f.empty_extraction
          AND EXISTS (
              SELECT 1
              FROM crawl.page_observations prior
              WHERE prior.page_id = f.page_id
                AND prior.observed_at < f.observed_at
                AND NOT prior.empty_extraction
          )
    ) AS regressions
FROM final f
"""
)

# A domain's first run is one with no observation from any EARLIER run. Not
# "no observations at all": this is asked while the current run is writing,
# so counting its own rows would make every run the first one and no domain
# would ever reach `broken`.
_FIRST_RUN = sa.text(
    """
SELECT NOT EXISTS (
    SELECT 1
    FROM crawl.page_observations o
    JOIN crawl.pages p ON p.id = o.page_id
    WHERE p.domain_id = :domain_id
      AND o.run_id <> :run_id
) AS first_run
"""
)

_UNKNOWN = sa.text(
    """
INSERT INTO crawl.unknown_pages (domain_id, url, reason)
VALUES (:domain_id, :url, :reason)
RETURNING id
"""
)

_DOMAIN_STATE = sa.text("SELECT state FROM crawl.domains WHERE id = :domain_id")

_SET_DOMAIN_STATE = sa.text(
    """
UPDATE crawl.domains
SET state = CAST(:state AS crawl.domain_state)
WHERE id = :domain_id
"""
)

_TOUCH_PAGE = sa.text("UPDATE crawl.pages SET last_crawled_at = :at WHERE id = :page_id")


class PostgresObservations:
    """Reads and writes `page_observations`, `unknown_pages` and the two
    columns of `domains` the detector moves."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def latest(self, page_id: PageId) -> PriorObservation | None:
        """The most recent observation of this page, across all runs.

        Across runs on purpose: ADR-0030's "an earlier observation" is the
        page's history, not this run's. A per-run lookup would make every
        page's first observation of every run a page with no prior.
        """
        async with self._engine.connect() as conn:
            row = (await conn.execute(_LATEST, {"page_id": page_id})).mappings().first()
        if row is None:
            return None
        return PriorObservation(
            id=ObservationId(row["id"]),
            content_hash=row["content_hash"],
            empty_extraction=row["empty_extraction"],
        )

    async def insert(self, observation: Observation) -> ObservationId:
        """One row. Append-only: nothing here updates an existing one."""
        params = _row(observation)
        async with self._engine.begin() as conn:
            observation_id = ObservationId((await conn.execute(_INSERT, params)).scalar_one())
            await conn.execute(
                _TOUCH_PAGE,
                {"page_id": observation.page_id, "at": observation.observed_at},
            )
        return observation_id

    async def record_unknown(self, domain_id: DomainId, url: str, reason: UnknownReason) -> int:
        """A page the operator has to look at (spec 001 §1, ADR-0027).

        Every empty page reaches the review inbox whether or not it counts
        toward the threshold — ADR-0030 narrows what is *evidence of a
        regression*, not what is reported.
        """
        async with self._engine.begin() as conn:
            return int(
                (
                    await conn.execute(
                        _UNKNOWN,
                        {"domain_id": domain_id, "url": url, "reason": reason.value},
                    )
                ).scalar_one()
            )

    async def health(self, run_id: RunId, domain_id: DomainId) -> RunHealth:
        """ADR-0030's three counts, plus whether this is a first run."""
        async with self._engine.connect() as conn:
            counts = (
                (await conn.execute(_HEALTH, {"run_id": run_id, "domain_id": domain_id}))
                .mappings()
                .one()
            )
            first_run = bool(
                (
                    await conn.execute(_FIRST_RUN, {"run_id": run_id, "domain_id": domain_id})
                ).scalar_one()
            )
        return RunHealth(
            pages_crawled=int(counts["pages_crawled"]),
            regressions=int(counts["regressions"]),
            empty_pages=int(counts["empty_pages"]),
            first_run=first_run,
        )

    async def domain_state(self, domain_id: DomainId) -> DomainState:
        async with self._engine.connect() as conn:
            return DomainState(
                (await conn.execute(_DOMAIN_STATE, {"domain_id": domain_id})).scalar_one()
            )

    async def set_domain_state(self, domain_id: DomainId, state: DomainState) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(_SET_DOMAIN_STATE, {"domain_id": domain_id, "state": state.value})


def _row(observation: Observation) -> dict[str, Any]:
    """An `Observation` as the columns spec 001 §1 defines.

    The typed core columns are filled from the extraction's field names; the
    rest of the extraction goes to `attributes`. A field the template calls
    `title` therefore lands in the `title` column and one it calls
    `shank_diameter` lands in JSONB, which is spec 001 §1's split and the
    reason the schema is not one JSONB blob.
    """
    fields = observation.fields
    amount, currency = _price(fields.get("price"))
    attributes = {
        name: _jsonable(value)
        for name, value in fields.items()
        if name not in _CORE_TEXT and name not in {"price", "category_path", "supplier"}
    }
    return {
        "page_id": observation.page_id,
        "run_id": observation.run_id,
        "template_id": observation.template_id,
        "observed_at": observation.observed_at,
        "http_status": observation.http_status,
        "content_hash": observation.content_hash,
        "strategy": observation.strategy.value if observation.strategy else None,
        "extraction_rung": (
            observation.extraction_rung.value if observation.extraction_rung else None
        ),
        "unchanged": observation.unchanged,
        "empty_extraction": observation.empty_extraction,
        "title": _text(fields.get("title")),
        "price_amount": amount,
        "price_currency": currency,
        "availability": _text(fields.get("availability")),
        "vendor": _text(fields.get("vendor")),
        "category_path": _path(fields.get("category_path")),
        "description": _text(fields.get("description")),
        "attributes": json.dumps(attributes),
        "supplier": json.dumps(_jsonable(fields.get("supplier")) or {}),
        "validation": json.dumps(
            {
                name: {"rule": result.rule.value, "ok": result.ok, "saw": result.saw}
                for name, result in observation.validation.items()
            }
        ),
    }


def _price(value: FieldValue) -> tuple[Decimal | None, str | None]:
    """The composite split into its two columns (spec 001 §1).

    A price whose currency could not be determined keeps its amount and
    leaves the currency NULL rather than assuming one: spec 003 §2 calls a
    guessed currency "a validation failure, not a guess", and the failure is
    already recorded in `validation`.
    """
    if value is None:
        return None, None
    if isinstance(value, dict):
        amount = value.get("amount")
        code = value.get("currency")
        return (
            amount if isinstance(amount, Decimal) else None,
            str(code) if code else None,
        )
    if isinstance(value, Decimal):
        return value, None
    return None, None


def _text(value: FieldValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _path(value: FieldValue) -> list[str] | None:
    """`category_path` is `TEXT[]`, so a single string becomes a one-element
    path rather than a column type error mid-crawl."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return None


def _jsonable(value: object) -> Any:
    """`Decimal` is not JSON. Serialised as its canonical string rather than
    as a float, because a float round-trip is how a price becomes
    `10.499999999999998`."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value
