"""The ordered chain (spec 003 §1).

```
1. structured   JSON-LD / microdata / RDFa      — no template needed
2. selector     the domain's approved template
3. llm_proposal onboarding/review only — NEVER at crawl time (ADR-0005)
4. unknown      routed to the review inbox with a reason
```

**This module owns the order and nothing else.** Adding a strategy is a class
and one entry in the tuple below — spec 003 §1 calls this the one place the
open/closed principle is worth the indirection, and the reason is that the
ordering *is* the design: each rung runs only if the cheaper one produced
nothing usable.

Rung 3 is deliberately absent. ADR-0005: the model proposes rules during
onboarding and never runs during a crawl, so a chain that could reach an LLM
at crawl time would be a defect however well it worked.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from spydra.domain.entities import ExtractedFields, Template
from spydra.domain.enums import Strategy
from spydra.domain.fetch import FetchedPage
from spydra.extraction.emptiness import is_blank
from spydra.extraction.hashing import is_substantive


class ExtractionStrategy(Protocol):
    """Spec 003 §1's Protocol."""

    name: Strategy

    async def extract(
        self, page: FetchedPage, template: Template | None = None
    ) -> ExtractedFields | None: ...


@dataclass(frozen=True, slots=True)
class ChainResult:
    """What the chain produced, and which rung produced it.

    `strategy` is `None` when no rung produced anything — the `unknown`
    outcome. The caller (`1.11`) turns that into an `unknown_pages` row with
    a reason, which is the only routing in this path and is deliberately
    outside the chain.
    """

    fields: ExtractedFields
    strategy: Strategy | None


class ExtractionChain:
    """Tries each rung in order until one produces something usable."""

    def __init__(self, strategies: Sequence[ExtractionStrategy]) -> None:
        self._strategies = tuple(strategies)

    async def extract(self, page: FetchedPage, template: Template | None = None) -> ChainResult:
        """The first rung whose extraction is **substantive** wins.

        A rung that returned nothing, or only blank values, is passed over.
        A rung that returned *something*, but nothing that survives
        normalisation (`is_substantive`), has not settled the page either.
        SEO plugins emit skeleton markup: a `Product` carrying only an
        `image`. Stopping there would leave the approved template
        unreachable.

        That second kind of result is kept as a fallback, not discarded.
        When no later rung does better it is still returned, so its image
        URLs reach the asset queue (`1.12`). The page is nonetheless an
        `empty_extraction` (ADR-0037): the fallback carries assets, not a
        verdict. The first such result wins, which keeps spec 003 §1's
        cheapest-first order.
        """
        fallback: ChainResult | None = None
        for strategy in self._strategies:
            fields = await strategy.extract(page, template)
            if fields is None:
                continue
            # Only on a 200, as before ADR-0037. On a 404 the rung that ran is
            # still the answer: the observation and its log line name it
            # (spec 009 §1), and a dead link is not a reason to try a rung
            # that cannot do better.
            if page.http_status == 200 and is_blank(fields):
                continue
            result = ChainResult(fields=fields, strategy=strategy.name)
            if is_substantive(fields):
                return result
            if fallback is None:
                fallback = result

        return fallback or ChainResult(fields={}, strategy=None)
