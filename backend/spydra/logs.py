"""Structured logging for the worker (spec 009 §1).

`structlog`, JSON to stdout, collected by `docker compose logs`. The stdlib
loggers the scheduler already uses (`politeness`, `robots`) are rendered by
the same pipeline, `extra=` fields included, so there is one format.

**Every crawl-path line carries its context without being handed it.** The
claim loop binds `run_id`, `domain`, `url` and `attempt` into contextvars
once per claim (`strategy` once it is known), and every line logged while
that page is being crawled, by any module, carries them (spec 009 §1: "a line
without the context needed to act on it is noise").

**Bodies cannot be logged by accident** (spec 009 §1 "never log"). Keys that
name a body, headers or a credential are dropped, and any string longer than
`_MAX_VALUE` is cut. A supplier's page is many kilobytes and nothing a worker
logs on purpose is; a test asserts the guarantee over a captured run
(spec 009 §5).
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Final

import structlog

_NEVER: Final[frozenset[str]] = frozenset(
    {"body", "html", "headers", "cookie", "cookies", "authorization", "password", "token"}
)
_MAX_VALUE: Final[int] = 300

# Third-party loggers held at `warning` even when the worker runs at `debug`.
# `httpcore2` logs raw response headers at debug, which is a `Set-Cookie` in
# the log: a credential, by spec 009 §1's list (found by running at debug).
_QUIET: Final[tuple[str, ...]] = (
    "httpx2",
    "httpcore2",
    "httpcore",
    "hpack",
    "sqlalchemy",
    "asyncio",
    "extruct",
)


def _redact(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in _NEVER:
            event[key] = "[redacted]"
            continue
        value = event[key]
        # A traceback is ours, not a supplier's, and cut short it is useless.
        if key == "exception":
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE:
            event[key] = f"{value[:_MAX_VALUE]}…[{len(value)} chars]"
    return event


def configure(level: str = "info") -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*shared, structlog.stdlib.ExtraAdder()],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            _redact,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
