"""Entities, value objects and pure logic. No I/O (AGENTS.md § Repository layout).

Re-exported here so callers write `from spydra.domain import Domain` rather
than reaching for a module path that may move. The submodules stay the place
to add things; this file is only the front door.
"""

from .entities import (
    DiscoveryRules,
    Domain,
    ExtractedFields,
    FieldRule,
    FieldValue,
    Observation,
    Rule,
    Template,
    Transform,
    ValidationResult,
)
from .enums import (
    DomainEvent,
    DomainState,
    FetchPath,
    PageKind,
    ProposedBy,
    RenderMode,
    RuleName,
    RunState,
    Strategy,
    TransformName,
    UnknownReason,
)
from .errors import Backpressure, FetchFailed, InvalidTransition, SpydraError
from .fetch import FetchedPage, FetchRequest
from .ids import DomainId, ObservationId, PageId, QueueItemId, RunId, TemplateId
from .lifecycle import can, legal_events, transition

__all__ = [
    "Backpressure",
    "DiscoveryRules",
    "Domain",
    "DomainEvent",
    "DomainId",
    "DomainState",
    "ExtractedFields",
    "FetchFailed",
    "FetchPath",
    "FetchRequest",
    "FetchedPage",
    "FieldRule",
    "FieldValue",
    "InvalidTransition",
    "Observation",
    "ObservationId",
    "PageId",
    "PageKind",
    "ProposedBy",
    "QueueItemId",
    "RenderMode",
    "Rule",
    "RuleName",
    "RunId",
    "RunState",
    "SpydraError",
    "Strategy",
    "Template",
    "TemplateId",
    "Transform",
    "TransformName",
    "UnknownReason",
    "ValidationResult",
    "can",
    "legal_events",
    "transition",
]
