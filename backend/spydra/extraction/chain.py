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

    @property
    def empty(self) -> bool:
        return self.strategy is None or not self.fields


class ExtractionChain:
    """Tries each rung in order until one produces something usable."""

    def __init__(self, strategies: Sequence[ExtractionStrategy]) -> None:
        self._strategies = tuple(strategies)

    async def extract(self, page: FetchedPage, template: Template | None = None) -> ChainResult:
        """The first rung that produces a non-empty extraction wins.

        **"Nothing usable" is `empty_extraction`, not `None`.** A rung that
        returns a mapping of all-empty values has not extracted anything, and
        stopping there would leave a selector template unreachable on a page
        whose JSON-LD is present but hollow — a shape that exists, because
        SEO plugins emit skeleton markup. The single predicate in
        `validation.py` is what both this and `1.11` use, so they cannot
        disagree about it (ADR-0027).
        """
        for strategy in self._strategies:
            fields = await strategy.extract(page, template)
            if fields is None:
                continue
            if empty_extraction(page.http_status, fields):
                continue
            return ChainResult(fields=fields, strategy=strategy.name)

        return ChainResult(fields={}, strategy=None)
