"""`render_mode = AUTO` — static first, the sidecar as the second chance.

Spec 012 §4 gives AUTO two behaviours, and only one of them can be built
here:

1. **The sidecar is unavailable.** Fall back to static and record that it
   happened, so a stopped `render` service leaves an AUTO domain crawling
   rather than stalling (spec 012 §4, TESTING.md §2). **This slice.**
2. **The static fetch succeeded but the extraction yielded nothing usable.**
   Retry once through the sidecar and record which path won. That predicate
   is `empty_extraction` from spec 003 §3, which does not exist until
   BUILD_PLAN `1.10`, and the orchestration belongs to the worker in `1.13`.
   **Named below and left unbuilt** rather than approximated, because an
   approximation of "nothing usable" is the exact failure mode ADR-0027
   removed requiredness to avoid.

Which means the name is slightly ahead of the behaviour today, and saying so
here is cheaper than someone discovering it from the code.
"""

from spydra.domain.enums import FetchPath
from spydra.domain.errors import Backpressure
from spydra.domain.fetch import FetchedPage, FetchRequest
from spydra.ports.fetcher import Fetcher


class AutoFetcher:
    """Composes the two adapters for an AUTO domain, and is itself a `Fetcher`.

    Being a `Fetcher` is what keeps the scheduler free of a branch on
    `render_mode`: it is handed something that fetches, and `1.13` picks which
    one per domain rather than asking what kind it is (ADR-0008).

    `path` reports `STATIC` because that is where AUTO starts. What actually
    served a given page is on the `FetchedPage`, which is the only place it
    can be correct — one adapter instance serves many pages.
    """

    path = FetchPath.STATIC

    def __init__(self, static: Fetcher, rendered: Fetcher) -> None:
        # Typed as the PORT, not as the two concrete adapters. That is the
        # whole point of ADR-0008 here: this composition does not know that a
        # browser exists on one side, and a test can hand it two fakes.
        self._static = static
        self._rendered = rendered

    async def fetch(self, request: FetchRequest) -> FetchedPage:
        """Fetch statically; fall back is the *rendered* path's failure mode.

        Note the direction. AUTO does not try rendered and fall back to
        static — it fetches static first because that is the cheap path, and
        spec 012 §4's "one wasted cheap fetch" is the stated cost of a wrong
        onboarding guess. So the only fallback this slice can observe is the
        one that happens when the rendered *second* attempt cannot be made.

        Raises:
            FetchFailed: the static fetch produced no response. Propagated,
                not swallowed — a dead supplier is not a sidecar problem, and
                converting it would hide a real failure behind a degraded
                one.
        """
        return await self._static.fetch(request)

    async def fetch_rendered_or_fall_back(self, request: FetchRequest) -> FetchedPage:
        """The second chance, for `1.13` to call when extraction found nothing.

        Separate from `fetch` because the decision to take it needs the
        extraction result, which the fetch layer does not have and must not
        guess at. `1.13` calls this; nothing else should.

        A sidecar that is full or down must not make an AUTO domain stall —
        that is what `RENDERED` does, and the difference between the two modes
        is precisely this fallback. So `Backpressure` is caught **here and
        only here**, and the static page is returned carrying
        `fell_back_from = RENDERED`, which `1.11` writes as
        `strategy = static_fallback`.
        """
        try:
            return await self._rendered.fetch(request)
        except Backpressure:
            static_page = await self._static.fetch(request)
            # dataclasses.replace would be tidier, but FetchedPage is
            # frozen+slots and replace() on it is no clearer than this.
            return FetchedPage(
                request_url=static_page.request_url,
                final_url=static_page.final_url,
                http_status=static_page.http_status,
                body=static_page.body,
                headers=static_page.headers,
                fetched_at=static_page.fetched_at,
                elapsed_ms=static_page.elapsed_ms,
                fetch_path=static_page.fetch_path,
                fell_back_from=FetchPath.RENDERED,
            )

    async def aclose(self) -> None:
        """Both pools. Closing one and leaking the other is the kind of thing
        that shows up as a hung SIGTERM in `1.13` rather than as an error."""
        await self._static.aclose()
        await self._rendered.aclose()
