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
from spydra.extraction.hashing import is_substantive
from spydra.extraction.validation import empty_extraction


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

        **"Nothing usable" is decided twice, and both tests are shared.**

        - A rung that returns a mapping of all-empty values has extracted
          nothing (`empty_extraction`, ADR-0027's one predicate), so the chain
          moves on.
        - A rung that returned *something*, but nothing that survives
          normalisation (`is_substantive`), has not settled the page either.
          SEO plugins emit skeleton markup: a `Product` carrying only an
          `image`. Stopping there would leave the approved template
          unreachable, and the page would hash like nothing at all, so it
          would be neither reported nor counted and would read `unchanged`
          for ever.

        That second kind of result is kept as a fallback, not discarded.
        When no later rung does better, it is still the best answer, and its
        image URLs still reach the asset queue (`1.12`). The first such
        result wins, which keeps spec 003 §1's cheapest-first order.
        """
        fallback: ChainResult | None = None
        for strategy in self._strategies:
            fields = await strategy.extract(page, template)
            if fields is None:
                continue
            if empty_extraction(page.http_status, fields):
                continue
            result = ChainResult(fields=fields, strategy=strategy.name)
            if is_substantive(fields):
                return result
            if fallback is None:
                fallback = result

        return fallback or ChainResult(fields={}, strategy=None)
