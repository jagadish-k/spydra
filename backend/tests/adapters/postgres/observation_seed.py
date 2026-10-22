"""Row builders for the observation suite (BUILD_PLAN 1.11).

Separate from `seed.py` — that file's docstring is about the frontier's
committed rows and ADR-0026, and these are pages, templates and
observations. Everything here COMMITS, for the same reason: the writer opens
its own transactions, so it cannot see a test's uncommitted rows.

`seed_observation` writes `page_observations` **directly**, not through
`PostgresObservations.insert`. That is deliberate: a test that built its
history with the adapter under test would be unable to detect an adapter
that writes the wrong `empty_extraction`, since the same bug would be in the
fixture and in the assertion.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Final, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.domain.ids import DomainId, PageId, RunId, TemplateId


async def seed_template(
    engine: AsyncEngine,
    domain_id: DomainId,
    *,
    name: str = "product",
    url_pattern: str = r"/catalog/.+",
    version: int = 1,
) -> TemplateId:
    """A template row, so an observation's FK resolves.

    The row's `extraction` JSONB is left empty: the entity the writer
    validates against is `tests/extraction/pages.py`'s, and a second copy of
    those selectors in SQL would be the drift that file exists to prevent.
    """
    async with engine.begin() as conn:
        return TemplateId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.templates
                            (domain_id, name, url_pattern, page_kind, version,
                             is_active, approved_at)
                        VALUES (:dom, :name, :pattern, 'product', :version, true, now())
                        RETURNING id
                        """
                    ),
                    {
                        "dom": int(domain_id),
                        "name": name,
                        "pattern": url_pattern,
                        "version": version,
                    },
                )
            ).scalar_one()
        )


async def seed_page(
    engine: AsyncEngine,
    domain_id: DomainId,
    url: str,
    *,
    template_id: TemplateId | None = None,
) -> PageId:
    async with engine.begin() as conn:
        return PageId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.pages
                            (domain_id, url, url_hash, page_kind, template_id)
                        VALUES (:dom, :url, :hash, 'product', :tpl)
                        RETURNING id
                        """
                    ),
                    {
                        "dom": int(domain_id),
                        "url": url,
                        "hash": url_hash(url),
                        "tpl": int(template_id) if template_id is not None else None,
                    },
                )
            ).scalar_one()
        )


class _Derived(Enum):
    """Sentinel: "the hash a row with this `empty` flag would carry"."""

    DERIVED = "derived"


DERIVED: Final = _Derived.DERIVED

# The hash a seeded non-empty prior carries. A literal digest rather than
# `hashing.content_hash(...)`: the module docstring's reason applies to the
# hasher as much as to the adapter, and nothing reads the value, only whether
# it is there (ADR-0037 reads the prior as `content_hash IS NOT NULL`).
_SEEDED_HASH: Final = hashlib.sha256(b"Hex Head Set Screw M8x40").digest()


async def seed_observation(
    engine: AsyncEngine,
    page_id: PageId,
    run_id: RunId,
    *,
    empty: bool,
    observed_at: datetime | None = None,
    content_hash: bytes | None | Literal[_Derived.DERIVED] = DERIVED,
    http_status: int = 200,
) -> int:
    """One historical observation, written as SQL (see the module docstring).

    `observed_at` defaults to an hour ago so a seeded prior is unambiguously
    EARLIER than anything the test writes next — ADR-0030's "an earlier
    observation" is a strict `<`, and two rows at the same microsecond is a
    coin toss the test would lose intermittently.

    **`content_hash` follows `empty` unless the test says otherwise.** Since
    1.11 the writer gives every substantive observation a hash and every
    other one none, so a non-empty row with no hash is a row it cannot
    produce. Seeding one by default made every "prior that worked" in this
    suite a legacy row, and ADR-0037 reads the prior from the hash. Pass
    `content_hash=None` with `empty=False` on purpose to get exactly that
    legacy shape: an image-only page written before ADR-0037.
    """
    at = observed_at or (datetime.now(UTC) - timedelta(hours=1))
    if content_hash is DERIVED:
        content_hash = None if empty else _SEEDED_HASH
    async with engine.begin() as conn:
        return int(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.page_observations
                            (page_id, run_id, observed_at, http_status,
                             content_hash, empty_extraction, title)
                        VALUES (:page, :run, :at, :status, :hash, :empty, :title)
                        RETURNING id
                        """
                    ),
                    {
                        "page": int(page_id),
                        "run": int(run_id),
                        "at": at,
                        "status": http_status,
                        "hash": content_hash,
                        "empty": empty,
                        # A row with a hash had something substantive in it,
                        # or the fixture would contradict its own hash. A
                        # legacy `empty = false` row with no hash is the
                        # image-only page, which had no title either.
                        "title": None if content_hash is None else "Hex Head Set Screw M8x40",
                    },
                )
            ).scalar_one()
        )


async def observation_rows(
    engine: AsyncEngine, page_id: PageId
) -> list[sa.Row[tuple[object, ...]]]:
    """Every observation of a page, oldest first — ADR-0007's history."""
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        """
                        SELECT id, content_hash, unchanged, empty_extraction,
                               strategy, extraction_rung, title, price_amount,
                               price_currency, attributes, validation
                        FROM crawl.page_observations
                        WHERE page_id = :page
                        ORDER BY observed_at, id
                        """
                    ),
                    {"page": int(page_id)},
                )
            ).all()
        )


async def unknown_rows(
    engine: AsyncEngine, domain_id: DomainId
) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        """
                        SELECT url, reason FROM crawl.unknown_pages
                        WHERE domain_id = :dom ORDER BY id
                        """
                    ),
                    {"dom": int(domain_id)},
                )
            ).all()
        )


async def domain_state(engine: AsyncEngine, domain_id: DomainId) -> str:
    async with engine.connect() as conn:
        return str(
            (
                await conn.execute(
                    sa.text("SELECT state::text FROM crawl.domains WHERE id = :id"),
                    {"id": int(domain_id)},
                )
            ).scalar_one()
        )
