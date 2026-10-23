"""One crawled page becomes one row, and the domain's health is re-read.

The order below is the slice (BUILD_PLAN `1.11`):

1. hash the **normalised** fields (spec 003 §4) — no hash at all when
   nothing survives normalisation;
2. compare against the page's previous hash — equal means a lightweight
   `unchanged` row. The emptiness verdict is computed from **this**
   extraction, before the fields are dropped, and never inherited;
3. write the observation (append-only, ADR-0007);
4. the asset URLs the extraction produced are enqueued — one `INSERT`, never
   a download (ADR-0003, spec 008 §1 step 1, `1.12`);
5. an `empty_extraction` on a 200, or a page with no template, goes to
   `unknown_pages` — every one of them, whether or not it counts as evidence
   (ADR-0027, ADR-0030);
6. re-read the domain's health and apply the event it calls for: `BREAK`
   past 20% of regressions, `NEVER_MATCHED` on a first run past 20% of
   empties. Only on a page that could have moved a ratio — see
   `_apply_health`.

**Step 2 is where the worst available bug in this slice lives, and the
ordering is what prevents it.** A lightweight row has no fields, and
`empty_extraction(200, {})` is `True` by definition — so a row whose only sin
is that the page did not change would be counted as an empty extraction, and
a perfectly stable catalogue would halt itself as a redesign on its second
run. The verdict is therefore computed from the real extraction *before* the
fields are dropped, and never re-derived from the row.

**The assets are enqueued even when the page is unchanged.** Asset URLs are
excluded from the hash (spec 003 §4), so an `unchanged` row can carry a
gallery that did change: a re-upload under new URLs. Skipping the enqueue
would make that change undetectable, and detecting it by content is what
spec 008 does with these rows. `page_current` skips `unchanged` rows, so the
gallery `5.2` links to one is not what the view returns; reconciling the two
is `5.2`'s, raised in `.tasks/fix-1.11-review-findings.md`. The cost is a
re-fetch of every unchanged gallery every run, which spec 008 §4's
hash-before-decode makes cheap but not free.

**No politeness and no queue state here.** The frontier closes the queue row
(`1.8`) and the politeness gate computes the delay (`1.9`); this writes what
was extracted. `1.13` calls both.
"""

from dataclasses import dataclass
from datetime import datetime

from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.domain.entities import Observation, Template
from spydra.domain.enums import DomainEvent, PageKind, Strategy, UnknownReason
from spydra.domain.fetch import FetchedPage
from spydra.domain.health import MINIMUM_PAGES_FOR_A_VERDICT, assess
from spydra.domain.ids import DomainId, ObservationId, PageId, RunId
from spydra.domain.lifecycle import can, transition
from spydra.extraction.assets import asset_urls
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
    # How many `asset_queue` rows this page added. The INSERTED count, not
    # the URL count: a re-crawl conflicts on UNIQUE (observation_id,
    # source_url) and adds nothing.
    assets_enqueued: int
    # A classification, not a write: the page's reason is reported on every
    # run it applies to. `inbox_opened` says whether this run actually added
    # an inbox row, which it does not while an earlier one is still open, so
    # a nightly dead link is one item for the operator rather than one per run.
    unknown_reason: UnknownReason | None
    inbox_opened: bool
    event: DomainEvent | None
    halted: bool


class ObservationWriter:
    """Writes observations and moves the domain when the run says to."""

    def __init__(self, observations: PostgresObservations, assets: PostgresAssets) -> None:
        self._observations = observations
        # Taken as a collaborator rather than left to `1.13` to call: the
        # rows are children of the observation, so the page path is one unit
        # of work. Surfacing the URLs for the caller to insert leaves a
        # silent failure mode where a refactor drops the second call and the
        # only symptom is an empty asset queue noticed months later.
        self._assets = assets

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
        # A NULL digest is "nothing comparable", never "the same as before":
        # two pages with nothing in them do not have equal content, and
        # without this an image-only or empty page would be `unchanged` from
        # its second run for ever (`hashing.content_hash`).
        unchanged = digest is not None and prior is not None and prior.content_hash == digest
        if unchanged:
            # Spec 003 §4's lightweight row: the fields are not repeated, and
            # `page_current` skips the row, so current state is still the
            # last full observation (ADR-0007).
            #
            # **`empty` is already decided, and that ordering is the guard.**
            # It was computed from the real extraction two lines up, so
            # emptying `fields` here cannot make a stable page look like an
            # empty one — `empty_extraction(200, {})` is `True` by
            # definition. The hash decides whether to repeat the fields; only
            # the predicate decides emptiness.
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
        # The extraction's URLs, not the lightweight row's: `fields` is empty
        # on an unchanged page and its gallery still has to be linked.
        enqueued = await self._assets.enqueue(run_id, observation_id, asset_urls(result.fields))

        reason = _reason(fetched.http_status, template, empty)
        opened = False
        if reason is not None:
            opened = (
                await self._observations.record_unknown(page.domain_id, page.url, reason)
                is not None
            )

        event, halted = (
            # ADR-0027 §3 and ADR-0039: only a page a product template
            # extracted is inside the threshold; anything else cannot change
            # the verdict and is not assessed.
            await self._apply_health(run_id, page.domain_id, empty=empty)
            if _extracted(template)
            else (None, False)
        )
        return WriteOutcome(
            observation_id=observation_id,
            observation=observation,
            assets_enqueued=enqueued,
            unknown_reason=reason,
            inbox_opened=opened,
            event=event,
            halted=halted,
        )

    async def _apply_health(
        self, run_id: RunId, domain_id: DomainId, *, empty: bool
    ) -> tuple[DomainEvent | None, bool]:
        """Re-read the ratio and move the domain if it calls for it.

        **After every page that could move it, not at the end of the run.**
        Spec 003 §3 halts a domain "mid-run"; assessed at the end, the
        detector would let a redesigned catalogue be crawled to completion
        and then report it, which is the data corruption it exists to
        prevent.

        **A non-empty page can only lower both ratios**: it grows the
        denominator, or replaces an earlier empty attempt of the same page.
        Past the minimum sample, it cannot be the page that trips the
        threshold, so it is not assessed. Assessing every page made the run
        quadratic: measured at 7 ms per call on a 3,400-page run, ~24 s, and
        ~40 min at 34,000 pages. The one non-empty page that *can* trip it is
        the one that brings the run up to the minimum, when 4 empties of 5
        is suddenly a verdict. Hence the bounded count.

        That reasoning assumes one write at a time. Two workers on one domain
        (`max_concurrency > 1`, or two replicas) can both commit non-empty
        pages 5 and 6 before either asks, and both then see a run already past
        the minimum. The verdict is then **delayed, not lost**: the next empty
        page on the domain is assessed and trips it.
        """
        if not empty and await self._observations.past_minimum(
            run_id, domain_id, MINIMUM_PAGES_FOR_A_VERDICT
        ):
            return None, False

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
    if empty and _extracted(template):
        return UnknownReason.EMPTY_EXTRACTION
    return None


def _extracted(template: Template | None) -> bool:
    """Was this page meant to yield product data? A listing template's page
    is for discovery (ADR-0039): it extracts nothing by design, so "empty"
    is not a verdict on it, neither for the inbox nor for the threshold."""
    return template is not None and template.page_kind is PageKind.PRODUCT
