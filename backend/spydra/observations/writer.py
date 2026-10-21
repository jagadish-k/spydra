"""One crawled page becomes one row, and the domain's health is re-read.

The order below is the slice (BUILD_PLAN `1.11`):

1. hash the **normalised** fields (spec 003 §4);
2. compare against the page's previous hash — equal means a lightweight
   `unchanged` row, with the **predecessor's emptiness verdict carried
   forward**;
3. write the observation (append-only, ADR-0007);
4. an `empty_extraction` on a 200, or a page with no template, goes to
   `unknown_pages` — every one of them, whether or not it counts as evidence
   (ADR-0027, ADR-0030);
5. re-read the domain's health and apply the event it calls for: `BREAK`
   past 20% of regressions, `NEVER_MATCHED` on a first run past 20% of
   empties.

**Step 2 is where the worst available bug in this slice lives, and the
ordering is what prevents it.** A lightweight row has no fields, and
`empty_extraction(200, {})` is `True` by definition — so a row whose only sin
is that the page did not change would be counted as an empty extraction, and
a perfectly stable catalogue would halt itself as a redesign on its second
run. The verdict is therefore computed from the real extraction *before* the
fields are dropped, and never re-derived from the row.

**No politeness and no queue state here.** The frontier closes the queue row
(`1.8`) and the politeness gate computes the delay (`1.9`); this writes what
was extracted. `1.13` calls both.
"""

from dataclasses import dataclass
from datetime import datetime

from spydra.adapters.postgres.observations import PostgresObservations
from spydra.domain.entities import Observation, Template
from spydra.domain.enums import DomainEvent, Strategy, UnknownReason
from spydra.domain.fetch import FetchedPage
from spydra.domain.health import assess
from spydra.domain.ids import DomainId, ObservationId, PageId, RunId
from spydra.domain.lifecycle import can, transition
from spydra.extraction.chain import ChainResult
from spydra.extraction.hashing import content_hash
from spydra.extraction.validation import empty_extraction, validate


@dataclass(frozen=True, slots=True)
class CrawledPage:
    """The page a worker is writing an observation for.

    Carried as its own small record rather than as four arguments: `1.13`
    holds all four already, and a (PageId, DomainId) pair passed positionally
    is the mistake `NewType` exists to catch but a reviewer cannot see.
    """

    id: PageId
    domain_id: DomainId
    url: str


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What the write did, for `1.13`'s logging and `2.8`'s run events.

    Returned rather than logged here: spec 009 §1 gives the worker a line
    budget, and a component that logs from two layers spends it twice.
    """

    observation_id: ObservationId
    observation: Observation
    unknown_reason: UnknownReason | None
    event: DomainEvent | None
    halted: bool


class ObservationWriter:
    """Writes observations and moves the domain when the run says to."""

    def __init__(self, observations: PostgresObservations) -> None:
        self._observations = observations

    async def record(
        self,
        *,
        page: CrawledPage,
        run_id: RunId,
        fetched: FetchedPage,
        result: ChainResult,
        template: Template | None,
        observed_at: datetime | None = None,
    ) -> WriteOutcome:
        """Step 1 to 5 of this module's docstring, in that order."""
        fields = result.fields
        digest = content_hash(fields)
        empty = empty_extraction(fetched.http_status, fields)

        prior = await self._observations.latest(page.id)
        unchanged = prior is not None and prior.content_hash == digest
        if unchanged:
            # Spec 003 §4's lightweight row: the fields are not repeated.
            #
            # **`empty` is already decided, and that ordering is the guard.**
            # It was computed from the real extraction two lines up, so
            # emptying `fields` here cannot make a stable page look like an
            # empty one — `empty_extraction(200, {})` is `True` by
            # definition, and a row carrying that verdict would be a
            # regression on every unchanged page of an unchanging catalogue.
            #
            # An earlier version also copied the predecessor's verdict on top
            # of this. Mutation proved that line could not fail: it agreed
            # with the computed verdict in every case a test could reach, so
            # it was a second mechanism for one decision — and it was the
            # WRONG one in the corner where they differ. A page whose only
            # field is an asset URL normalises to `{}` (spec 003 §4 excludes
            # asset URLs), so it hashes like an empty page while the
            # predicate correctly says it has content; inheriting would have
            # marked it empty. The hash decides whether to repeat the fields;
            # only the predicate decides emptiness.
            fields = {}

        observation = Observation(
            page_id=page.id,
            run_id=run_id,
            template_id=template.id if template is not None else None,
            observed_at=observed_at or fetched.fetched_at,
            http_status=fetched.http_status,
            # Spec 012 §4: an AUTO domain that wanted a rendered fetch and
            # could not have one records `static_fallback`. The rung it
            # actually used travels in `extraction_rung` — one column cannot
            # hold both answers (`1.7` open question 2).
            strategy=(Strategy.STATIC_FALLBACK if fetched.degraded else result.strategy),
            content_hash=digest,
            fields=fields,
            validation=(
                validate(result.fields, template.extraction) if template is not None else {}
            ),
            unchanged=unchanged,
            empty_extraction=empty,
            extraction_rung=result.strategy,
        )
        observation_id = await self._observations.insert(observation)

        reason = _reason(fetched.http_status, template, empty)
        if reason is not None:
            await self._observations.record_unknown(page.domain_id, page.url, reason)

        event, halted = await self._apply_health(run_id, page.domain_id)
        return WriteOutcome(
            observation_id=observation_id,
            observation=observation,
            unknown_reason=reason,
            event=event,
            halted=halted,
        )

    async def _apply_health(
        self, run_id: RunId, domain_id: DomainId
    ) -> tuple[DomainEvent | None, bool]:
        """Re-read the ratio and move the domain if it calls for it.

        **After every page, not at the end of the run.** Spec 003 §3 halts a
        domain "mid-run"; assessed at the end, the detector would let a
        redesigned catalogue be crawled to completion and then report it,
        which is the data corruption it exists to prevent.
        """
        health = await self._observations.health(run_id, domain_id)
        event = assess(health)
        if event is None:
            return None, False

        state = await self._observations.domain_state(domain_id)
        if not can(state, event):
            # Already halted: the ratio stays over the threshold for every
            # page after the one that tripped it, and `transition` raises on
            # an edge that does not exist. A domain that is already `broken`
            # is not a second failure to report.
            return event, False

        await self._observations.set_domain_state(domain_id, transition(state, event))
        return event, True


def _reason(http_status: int, template: Template | None, empty: bool) -> UnknownReason | None:
    """Why this page needs an operator, or `None` if it does not.

    **Only on a 200.** A 404 that yielded nothing is a dead link, not a
    template problem — the same reasoning that puts the status inside
    `empty_extraction` (ADR-0027). Routing non-200s here would fill the
    review inbox with every broken link on the site and bury the one page
    that matters.

    `no_template` outranks `empty_extraction`: a page with no template has a
    configuration gap, and reporting it as an empty extraction would send the
    operator to review a selector that does not exist (ADR-0027 §3).
    """
    if http_status != 200:
        return None
    if template is None:
        return UnknownReason.NO_TEMPLATE
    if empty:
        return UnknownReason.EMPTY_EXTRACTION
    return None
