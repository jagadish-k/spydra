"""`robots.txt`, once per domain per run (spec 002 §5).

Three rules, and the third is the one people get wrong:

1. `Disallow` is honoured for our user-agent, falling back to `*`.
2. **`Crawl-delay` is a FLOOR.** It raises a configured delay and never
   lowers it. A site's stated delay is the minimum it is willing to tolerate,
   not a target to speed up to.
3. **A 5xx or a timeout fails CLOSED** — the domain is disallowed for the
   run. A 4xx means no restrictions. Failing closed is correct when the site
   cannot tell you its rules: the alternative is crawling a site that was
   about to say "don't".

Parsed with `urllib.robotparser` from the standard library, fed lines rather
than a URL so it never touches the network itself — the fetch goes through
the `Fetcher` port like any other request, carrying the honest user-agent
(ADR-0004). Spec 002 §5 makes that fetch part of the politeness path rather
than a special case bolted on beside it.
"""

import logging
from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

from spydra.domain.errors import FetchFailed
from spydra.domain.fetch import FetchRequest
from spydra.ports.fetcher import Fetcher

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RobotsRules:
    """What one domain's `robots.txt` said, for the duration of one run.

    `allowed_at_all = False` is the fail-closed case and is deliberately
    distinct from "a rule disallows this particular path": the first stops
    the domain for the run, the second skips a URL.
    """

    allowed_at_all: bool
    crawl_delay_s: float | None
    _parser: RobotFileParser | None = None
    _user_agent: str = "*"

    def can_fetch(self, url: str) -> bool:
        if not self.allowed_at_all:
            return False
        if self._parser is None:
            return True
        return self._parser.can_fetch(self._user_agent, url)

    @classmethod
    def unrestricted(cls) -> RobotsRules:
        """A 4xx, or `respect_robots = false`. Nothing is disallowed."""
        return cls(allowed_at_all=True, crawl_delay_s=None)

    @classmethod
    def closed(cls) -> RobotsRules:
        """A 5xx or a timeout: the site could not tell us its rules."""
        return cls(allowed_at_all=False, crawl_delay_s=None)


class RobotsCache:
    """One `robots.txt` fetch per domain per run.

    Keyed by `(run_id, host)` rather than by host alone: spec 002 §5 says
    "once per domain per run, cached for the run's duration", so a second run
    must re-read a file the first one cached — otherwise a site that changed
    its rules between runs is crawled against the old ones for as long as the
    process lives.
    """

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher
        self._cache: dict[tuple[int, str], RobotsRules] = {}
        self.fetch_count = 0

    async def rules_for(
        self,
        run_id: int,
        host: str,
        user_agent: str,
        *,
        respect_robots: bool = True,
        scheme: str = "https",
    ) -> RobotsRules:
        if not respect_robots:
            # Spec 002 §5: "an operator override, logged every time it takes
            # effect". Every time, not once per run — the operator chose to
            # ignore a site's stated rules and each crawl under that override
            # should be attributable.
            log.warning(
                "robots_override", extra={"host": host, "run_id": run_id, "respect_robots": False}
            )
            return RobotsRules.unrestricted()

        key = (run_id, host)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        rules = await self._fetch(host, user_agent, scheme)
        self._cache[key] = rules
        return rules

    async def _fetch(self, host: str, user_agent: str, scheme: str) -> RobotsRules:
        url = f"{scheme}://{host}/robots.txt"
        self.fetch_count += 1
        try:
            page = await self._fetcher.fetch(FetchRequest(url=url, user_agent=user_agent))
        except FetchFailed:
            # Spec 002 §5 names "a 5xx or a timeout"; a FetchFailed from the
            # port IS the timeout case, so it belongs on the fail-closed
            # branch rather than being an unhandled path that crashes the
            # claim loop.
            log.warning("robots_unavailable", extra={"host": host, "reason": "fetch_failed"})
            return RobotsRules.closed()

        if page.http_status >= 500:
            log.warning("robots_unavailable", extra={"host": host, "status": page.http_status})
            return RobotsRules.closed()

        if page.http_status >= 400:
            # No file, or no permission to read it: no restrictions.
            return RobotsRules.unrestricted()

        return self._parse(page.body, user_agent)

    @staticmethod
    def _parse(body: str, user_agent: str) -> RobotsRules:
        parser = RobotFileParser()
        parser.parse(body.splitlines())

        # Our token first, `*` second (spec 002 §5). `crawl_delay` returns
        # None when neither matches, which is "no floor" rather than "no
        # delay" — the configured value stands.
        delay = parser.crawl_delay(user_agent)
        if delay is None:
            delay = parser.crawl_delay("*")

        return RobotsRules(
            allowed_at_all=True,
            crawl_delay_s=float(delay) if delay is not None else None,
            _parser=parser,
            _user_agent=user_agent,
        )
