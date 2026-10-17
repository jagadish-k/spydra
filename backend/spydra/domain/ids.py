"""Identity types.

`NewType` over `int` rather than bare `int`: these are BIGSERIAL keys and
mypy --strict will not let a PageId be passed where a RunId belongs, which is
the one mistake that is both easy to make and invisible in a test fixture
where every id happens to be 1.
"""

from typing import NewType

DomainId = NewType("DomainId", int)
TemplateId = NewType("TemplateId", int)
PageId = NewType("PageId", int)
RunId = NewType("RunId", int)
ObservationId = NewType("ObservationId", int)
QueueItemId = NewType("QueueItemId", int)
