"""`crawl.pages`: one row per URL a domain has ever had crawled (spec 001 §1).

The crawl queue is per run and pages are for ever, so the first crawl of a URL
creates its page and every later one finds it. `template_id` follows the
template that matched this time: a URL that changes shape changes template,
and the observation records the version that produced it (AGENTS.md rule 12).
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.domain.enums import PageKind
from spydra.domain.ids import DomainId, PageId, TemplateId

# `DO UPDATE`, not `DO NOTHING`: the template and kind can change between
# runs, and `RETURNING` only returns a row the statement touched, so DO NOTHING
# would need a second SELECT for every page already known.
_UPSERT = sa.text(
    """
INSERT INTO crawl.pages (domain_id, url, url_hash, page_kind, template_id, depth)
VALUES (:domain_id, :url, :url_hash, :page_kind, :template_id, :depth)
ON CONFLICT (domain_id, url_hash) DO UPDATE
SET template_id = EXCLUDED.template_id,
    page_kind = EXCLUDED.page_kind
RETURNING id
"""
)


class PostgresPages:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(
        self,
        domain_id: DomainId,
        url: str,
        *,
        depth: int,
        template_id: TemplateId | None,
        page_kind: PageKind | None,
    ) -> PageId:
        async with self._engine.begin() as conn:
            return PageId(
                (
                    await conn.execute(
                        _UPSERT,
                        {
                            "domain_id": int(domain_id),
                            "url": url,
                            "url_hash": url_hash(url),
                            "page_kind": page_kind.value if page_kind else None,
                            "template_id": int(template_id) if template_id else None,
                            "depth": depth,
                        },
                    )
                ).scalar_one()
            )
