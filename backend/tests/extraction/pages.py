"""The fixture pages and the template `1.10` and `1.11` both extract with.

Shared rather than copied. `1.11`'s redesign test only means anything if its
template is the *same* one the chain tests prove against
`vantage-abrasives/product.html` — a second copy here and the redesign test
would pass against a template nobody ever approved, which is the vacuous
shape `1.10`'s own review found twice.

`PAGES` resolves from this file, so a test anywhere in the tree reaches the
same `1.4` fixtures.
"""

from datetime import UTC, datetime
from pathlib import Path

from spydra.domain.entities import (
    DiscoveryRules,
    FieldRule,
    Rule,
    Template,
    Transform,
)
from spydra.domain.enums import (
    FetchPath,
    PageKind,
    ProposedBy,
    RuleName,
    TransformName,
)
from spydra.domain.fetch import FetchedPage
from spydra.domain.ids import DomainId, TemplateId

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"


def page(path: str, url: str, status: int = 200) -> FetchedPage:
    body = (PAGES / path).read_text()
    return FetchedPage(
        request_url=url,
        final_url=url,
        http_status=status,
        body=body,
        headers={},
        fetched_at=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        elapsed_ms=40,
        fetch_path=FetchPath.STATIC,
    )


def vantage_template() -> Template:
    """The template an operator would approve for `vantage-abrasives.test`.

    Written from the fixture's markup, which is what a real template is —
    and `northfield/product-redesigned.html` is the same shape with the
    class names changed, which is how the redesign test works.
    """
    return Template(
        id=TemplateId(1),
        domain_id=DomainId(1),
        name="vantage product",
        # A string, despite the entity docstring saying "a compiled pattern,
        # not a string" — the annotation is `str`. Raised in the task file.
        url_pattern=r"/catalog/.+",
        page_kind=PageKind.PRODUCT,
        version=1,
        is_active=True,
        discovery=DiscoveryRules(),
        extraction={
            "title": FieldRule(
                selector=".product__title",
                transform=(Transform(TransformName.TRIM),),
                validation=(Rule(RuleName.NON_EMPTY),),
            ),
            "price": FieldRule(
                selector=".product__price",
                validation=(Rule(RuleName.CURRENCY),),
            ),
            "availability": FieldRule(selector=".product__availability"),
            "vendor": FieldRule(selector=".product__vendor"),
            "images": FieldRule(
                selector=".gallery__image",
                attr="src",
                many=True,
                transform=(Transform(TransformName.ABSOLUTE_URL),),
                validation=(Rule(RuleName.MIN_COUNT, 1),),
            ),
        },
        proposed_by=ProposedBy.HUMAN,
    )
