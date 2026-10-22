"""Extraction: an ordered chain of strategies, cheapest first (spec 003).

`chain.py` owns the order. `validation.py` owns the one `empty_extraction`
predicate that the `auto` fallback, the `unknown_pages` reason and the
`broken` threshold all share (ADR-0027) — three copies would disagree about
what "nothing came back" means, and the disagreement would surface as a
healthy domain stopping itself.
"""

from .chain import ChainResult, ExtractionChain, ExtractionStrategy
from .strategies.selector import SelectorStrategy
from .strategies.structured import StructuredStrategy
from .validation import empty_extraction, is_empty, validate, validate_field

__all__ = [
    "ChainResult",
    "ExtractionChain",
    "ExtractionStrategy",
    "SelectorStrategy",
    "StructuredStrategy",
    "empty_extraction",
    "is_empty",
    "validate",
    "validate_field",
]
