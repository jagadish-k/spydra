"""One claimed URL, crawled end to end (BUILD_PLAN 1.13).

This is the orchestration every earlier slice named and left: it composes the
politeness gate (`1.9`), robots (`1.9`), both fetchers and AUTO (`1.6`/`1.7`),
the chain (`1.10`) and the writer (`1.11`/`1.12`). It decides nothing those
components already decide. **What it owns is the order**, and the order is
where the politeness guarantees live:

1. robots before any request to the page;
2. one request per claim, plus at most AUTO's second chance, which takes the
   page already in hand (`1.7`);
3. the gate's decision is written in the same transaction that closes the
   row (spec 002 §2), and it is computed from the **last** response the
   supplier sent, since that is the request it is about;
4. a 403 is never retried (ADR-0004); three consecutive pause the domain and
   abandon its queue.

| Outcome                        | Row                    | Observation | Inbox         |
| ------------------------------ | ---------------------- | ----------- | ------------- |
| sidecar full (`Backpressure`)  | released, no penalty   | —           | —             |
| no response (`FetchFailed`)    | retried, then `failed` | —           | `fetch_error` |
| 429 / 503 / other 5xx          | retried, then `failed` | —           | `fetch_error` |
| 403                            | `failed`               | —           | —             |
| robots disallows               | `failed`, no request   | —           | —             |
| anything else (2xx, 404, 410…) | `done`                 | written     | the writer's  |

`fetch_error` is recorded only once the row has failed for good, not on each
attempt.

**Why no observation for a refusal or an outage.** An observation is a fact
about the page. A 404 is one (the page is gone), but a 403, a 429 or a 500 is
a fact about the request, and writing it would add a non-empty page to
ADR-0030's denominator for a page nobody saw.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import structlog

from spydra.adapters.http.auto_fetcher import AutoFetcher
from spydra.adapters.postgres.domains import PostgresDomains
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.adapters.postgres.pages import PostgresPages
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.adapters.postgres.templates import PostgresTemplates, matching
from spydra.discovery.canonical import canonical_link
from spydra.discovery.links import discover
from spydra.domain.entities import Domain, Template
from spydra.domain.enums import DomainEvent, RenderMode, UnknownReason
from spydra.domain.errors import Backpressure, FetchFailed
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.domain.urls import canonical_url
from spydra.extraction.chain import ChainResult, ExtractionChain
from spydra.extraction.validation import empty_extraction
from spydra.observations.writer import CrawledPage, ObservationWriter
from spydra.ports.clock import Clock
from spydra.ports.fetcher import Fetcher
from spydra.ports.frontier import MAX_ATTEMPTS, ClaimedUrl, Completion, Frontier, QueueItemState
from spydra.scheduler.politeness import (
    RATE_LIMIT_STATUSES,
    Decision,
    DomainPoliteness,
    PolitenessGate,
)
from spydra.scheduler.robots import RobotsCache, RobotsRules

log = structlog.get_logger(__name__)

# Spec 012 §4 wants a stalled rendered domain *reported*. Every claim of it
# fails the same way while the sidecar is down, so the report is rate-limited
# rather than one line per claim, which would break spec 009 §5's budget.
RENDER_UNAVAILABLE_EVERY_S = 60.0


@dataclass(frozen=True, slots=True)
class Fetchers:
    """The three ways a page can be fetched, one per `render_mode`.

    `rendered` is the sidecar behind the shared `RenderBudget`, and `auto`
    composes `static` with that same budgeted instance, so an AUTO second
    chance spends a rendered slot like any other render.
    """

    static: Fetcher
    rendered: Fetcher
    auto: AutoFetcher

    def for_mode(self, mode: RenderMode) -> Fetcher:
        if mode is RenderMode.RENDERED:
            return self.rendered
        if mode is RenderMode.AUTO:
            return self.auto
        return self.static


@dataclass(frozen=True, slots=True)
class Repositories:
    """Everything the crawl reads or writes in Postgres, besides the queue."""

    domains: PostgresDomains
    pages: PostgresPages
    templates: PostgresTemplates
    observations: PostgresObservations
    runs: PostgresRuns


class PageCrawler:
    def __init__(
        self,
        *,
        frontier: Frontier,
        repositories: Repositories,
        writer: ObservationWriter,
        chain: ExtractionChain,
        gate: PolitenessGate,
        robots: RobotsCache,
        fetchers: Fetchers,
        user_agent: str,
        clock: Clock,
    ) -> None:
        self._frontier = frontier
        self._repos = repositories
        self._writer = writer
        self._chain = chain
        self._gate = gate
        self._robots = robots
        self._fetchers = fetchers
        self._user_agent = user_agent
        self._clock = clock
        self._render_reported_at: float | None = None

    async def crawl(self, item: ClaimedUrl) -> bool:
        """Crawl one claimed URL. `True` asks the loop to back off before its
        next claim: the row went back unfetched (spec 002 §6), and claiming
        again at once would take the same row from the same domain, which is
        still the most eligible, at hundreds of cycles a second."""
        domain = await self._repos.domains.get(item.domain_id)
        # Spec 009 §1's `domain` is what an operator reads: the host.
        structlog.contextvars.bind_contextvars(domain=domain.host)
        user_agent = domain.user_agent or self._user_agent
        rules = await self._robots.rules_for(
            int(item.run_id),
            domain.host,
            user_agent,
            respect_robots=domain.respect_robots,
            scheme=urlsplit(item.url).scheme or "https",
        )
        state = _politeness(domain, rules)

        if not rules.can_fetch(item.url):
            # No request was made, so the politeness state is left exactly
            # as it was: nothing happened that the gate could decide about.
            log.debug("robots_disallowed")
            await self._close(item, QueueItemState.FAILED, _unchanged(domain))
            return False

        request = FetchRequest(url=item.url, user_agent=user_agent)
        try:
            fetched = await self._fetchers.for_mode(domain.render_mode).fetch(request)
        except Backpressure:
            # Spec 002 §6: our sidecar is full. Not the supplier's doing, so
            # no penalty, and the gate is given back so another worker can try.
            self._report_render_unavailable()
            await self._frontier.release(item)
            return True
        except FetchFailed:
            await self._retry_or_fail(item, self._gate.on_fetch_error(state), "fetch_failed")
            return False

        template = matching(await self._repos.templates.active_for(domain.id), _path(item.url))
        result: ChainResult | None = None
        # Only a page a template was meant to extract. A listing or category
        # page with no template has no selector a render could feed, and
        # rendering every one would be a second request to the supplier per
        # page for nothing.
        if (
            domain.render_mode is RenderMode.AUTO
            and template is not None
            and fetched.http_status == 200
        ):
            result = await self._chain.extract(fetched, template)
            if empty_extraction(fetched.http_status, result.fields):
                fetched, result = await self._second_chance(request, fetched, template, result)

        decision = self._gate.for_status(state, fetched.http_status)
        status = fetched.http_status
        if status == 403:
            log.warning("refused", status=status, consecutive_403s=decision.consecutive_403s)
            # Only a 403 this claim actually recorded counts toward the pause.
            if await self._close(item, QueueItemState.FAILED, decision):
                await self._pause_if_blocked(item, decision)
            return False
        if status in RATE_LIMIT_STATUSES:
            # Spec 009 §1 puts "backoff applied" at warning.
            log.warning("backoff", status=status, crawl_delay_ms=decision.crawl_delay_ms)
        if status in RATE_LIMIT_STATUSES or status >= 500:
            await self._retry_or_fail(item, decision, "server_refused", status=status)
            return False

        if result is None:
            result = await self._chain.extract(fetched, template)
        await self._observe(item, domain, fetched, template, result)
        await self._close(item, QueueItemState.DONE, decision)
        return False

    async def abort(self, item: ClaimedUrl) -> None:
        """Close a row whose crawl raised something unexpected.

        Treated like a 5xx: retried up to the attempt limit, with no penalty
        to the domain, because a bug of ours is not the supplier's doing.
        Left to the lease sweep instead, the row would hold the domain's
        `in_flight` for two minutes on every crash.

        A crash after the row was already closed changes nothing: the
        completion is fenced on the lease. And a crash is not a
        `fetch_error`, which spec 001 §1 defines as "non-2xx or timeout", so
        it never reaches the inbox; it is an error line with a traceback.
        """
        domain = await self._repos.domains.get(item.domain_id)
        state = _politeness(domain, RobotsRules.unrestricted())
        await self._retry_or_fail(
            item, self._gate.on_server_error(state), "crawl_crashed", inbox=False
        )

    async def _second_chance(
        self,
        request: FetchRequest,
        fetched: FetchedPage,
        template: Template | None,
        result: ChainResult,
    ) -> tuple[FetchedPage, ChainResult]:
        """Spec 012 §4: AUTO retries through the sidecar when the static page
        yielded nothing usable.

        **"Nothing usable" is `empty_extraction`**, the same function the
        inbox reason and the threshold call (ADR-0027, ADR-0037). A
        JS-dependent page whose server HTML carries an image-only SEO stub is
        an empty extraction, so it gets its browser retry.
        """
        try:
            rendered = await self._fetchers.auto.fetch_rendered_or_fall_back(request, fetched)
        except FetchFailed:
            # The supplier answered the static request; a render that got no
            # response does not undo that, and the static page is kept.
            log.debug("second_chance_failed")
            return fetched, result
        if rendered is fetched:
            return fetched, result
        return rendered, await self._chain.extract(rendered, template)

    async def _observe(
        self,
        item: ClaimedUrl,
        domain: Domain,
        fetched: FetchedPage,
        template: Template | None,
        result: ChainResult,
    ) -> None:
        # Spec 004 §2 step 7: the page's own canonical names the `pages` row,
        # so two URLs for one product are one page. Resolved against the URL
        # the body came from (redirects are followed), and honoured only on a
        # 200 and only on this domain's host: a redirect off-host must never
        # file another site's page under this domain.
        page_url = canonical_url(item.url)
        if fetched.http_status == 200:
            named = canonical_link(fetched.body, fetched.final_url)
            if named is not None and _same_host(named, item.url):
                page_url = named
        page_id = await self._repos.pages.upsert(
            domain.id,
            page_url,
            depth=item.depth,
            template_id=template.id if template else None,
            page_kind=template.page_kind if template else None,
        )
        outcome = await self._writer.record(
            page=CrawledPage(id=page_id, domain_id=domain.id, url=page_url),
            run_id=item.run_id,
            fetched=fetched,
            result=result,
            template=template,
        )
        structlog.contextvars.bind_contextvars(strategy=outcome.observation.strategy)
        log.debug(
            "page_crawled",
            status=fetched.http_status,
            fetch_path=fetched.fetch_path,
            unchanged=outcome.observation.unchanged,
            empty=outcome.observation.empty_extraction,
            assets_enqueued=outcome.assets_enqueued,
            inbox=outcome.unknown_reason if outcome.inbox_opened else None,
        )
        if outcome.halted:
            # ADR-0030 moved the domain out of `active`. Its remaining rows
            # will never be claimed, so they are recorded as work not done
            # and the run can finish instead of waiting on them for ever.
            abandoned = await self._frontier.abandon_domain(item.run_id, domain.id)
            log.error(
                "domain_halted",
                verdict=outcome.event,
                abandoned=abandoned,
                action="review the domain's template against its current pages",
            )
            return
        await self._discover(item, domain, fetched, template)

    async def _discover(
        self, item: ClaimedUrl, domain: Domain, fetched: FetchedPage, template: Template | None
    ) -> None:
        """Spec 004 §1: enqueue what the template's discovery rules select.

        Before the row is closed, so the run cannot look drained between this
        page completing and its links arriving. Never on a halted domain: its
        new rows would never be claimed and the run would never finish.
        """
        if template is None or fetched.http_status != 200:
            return
        found = discover(
            fetched.body,
            fetched.final_url,
            template.discovery,
            host=domain.host,
            depth=item.depth,
            max_depth=domain.max_depth,
            domain_deny=domain.deny_patterns,
        )
        links = found.links()
        added = await self._frontier.enqueue(item.run_id, domain.id, links) if links else 0
        log.debug(
            "links_discovered",
            accepted=len(links),
            enqueued=added,
            rejected={key: r.count for key, r in found.rejected.items()},
        )

    async def _retry_or_fail(
        self,
        item: ClaimedUrl,
        decision: Decision,
        why: str,
        *,
        inbox: bool = True,
        **detail: Any,
    ) -> None:
        final = item.attempts >= MAX_ATTEMPTS
        state = QueueItemState.FAILED if final else QueueItemState.PENDING
        if not await self._close(item, state, decision):
            return
        if final and inbox:
            await self._repos.observations.record_unknown(
                item.domain_id, item.url, UnknownReason.FETCH_ERROR
            )
            log.warning(f"{why}_gave_up", **detail)
        else:
            log.debug(f"{why}_will_retry", **detail)

    async def _pause_if_blocked(self, item: ClaimedUrl, decision: Decision) -> None:
        if not decision.pause_domain:
            return
        moved = await self._repos.domains.apply(item.domain_id, DomainEvent.BLOCK)
        abandoned = 0
        if decision.abandon_queue:
            abandoned = await self._frontier.abandon_domain(item.run_id, item.domain_id)
        if moved is not None:
            log.error(
                "domain_paused",
                reason="three consecutive 403s",
                abandoned=abandoned,
                action="check whether the site is blocking the crawler before resuming",
            )
        await self._finish(item)

    async def _close(
        self, item: ClaimedUrl, state: QueueItemState, decision: Decision | Completion
    ) -> bool:
        """`False` when this claim no longer held the row, so nothing that
        depends on having closed it (an inbox row, a run finish) follows."""
        if not await self._frontier.complete(item, _completion(state, decision)):
            log.warning("lease_lost", action="none; the row's current holder completes it")
            return False
        await self._finish(item)
        return True

    def _report_render_unavailable(self) -> None:
        now = self._clock.monotonic()
        last = self._render_reported_at
        if last is None or now - last >= RENDER_UNAVAILABLE_EVERY_S:
            self._render_reported_at = now
            log.warning(
                "render_unavailable",
                action="check the render service; rendered domains are stalled until it answers",
            )

    async def _finish(self, item: ClaimedUrl) -> None:
        stats = await self._repos.runs.finish_if_drained(item.run_id)
        if stats is not None:
            # About the run, not the page that happened to close it.
            with structlog.contextvars.bound_contextvars(url=None, attempt=None, strategy=None):
                log.info("run_finished", stats=stats)


def _politeness(domain: Domain, rules: RobotsRules) -> DomainPoliteness:
    """The gate's input. Robots' `Crawl-delay` raises both the delay and the
    floor the decay stops at, and never lowers either (spec 002 §5)."""
    return DomainPoliteness(
        crawl_delay_ms=PolitenessGate.apply_robots_floor(
            domain.crawl_delay_ms, rules.crawl_delay_s
        ),
        consecutive_failures=domain.consecutive_failures,
        consecutive_403s=domain.consecutive_403s,
        floor_ms=PolitenessGate.apply_robots_floor(
            domain.configured_crawl_delay_ms, rules.crawl_delay_s
        ),
    )


def _unchanged(domain: Domain) -> Completion:
    return Completion(
        state=QueueItemState.FAILED,
        next_eligible_at=domain.next_eligible_at,
        crawl_delay_ms=domain.crawl_delay_ms,
        consecutive_failures=domain.consecutive_failures,
        consecutive_403s=domain.consecutive_403s,
    )


def _completion(state: QueueItemState, source: Decision | Completion) -> Completion:
    return Completion(
        state=state,
        next_eligible_at=source.next_eligible_at,
        crawl_delay_ms=source.crawl_delay_ms,
        consecutive_failures=source.consecutive_failures,
        consecutive_403s=source.consecutive_403s,
    )


def _path(url: str) -> str:
    """Path plus query of the **canonical** URL: what `templates.url_pattern`
    is matched against (spec 001 §1). The queue fetches the URL as written
    (2.2), so `/shop/cutting/` and `/shop/cutting` are one page, and a
    pattern written for one must match the other."""
    parts = urlsplit(canonical_url(url))
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _same_host(url: str, other: str) -> bool:
    return urlsplit(canonical_url(url)).netloc == urlsplit(canonical_url(other)).netloc
