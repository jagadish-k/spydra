"""Approved templates, as the crawl path reads them (BUILD_PLAN 1.13).

**The JSONB shape is spec 013 §2's `FieldCandidate`**, the unit every
authoring mode produces, so a template written by the YAML loader (`1.14`)
and one approved from a draft (phase 3) are the same bytes:

```jsonc
{ "selector": ".price", "attr": "text", "many": false,
  "transform": ["strip_currency", {"name": "pairs", "args": ["th", "td"]}],
  "validation": ["currency", {"name": "min_count", "arg": 3}],
  "fallback": "[itemprop=price]" }
```

A step with no argument is its bare name; one with arguments is an object.

**`required` is read from nowhere** (ADR-0027). Prior versions may still carry
the key, and that is the reason it stays in the JSONB (spec 001 §3); nothing
here decodes it, so it cannot influence a crawl. `1.14`'s loader is what
refuses `required: true`.

**A template whose pattern does not compile fails when it is read**, not when
the hundredth URL is matched against it: the entity's docstring asks for that,
and a crawl that fails mid-run on a template is a crawl that half-happened.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.domain.entities import DiscoveryRules, FieldRule, Rule, Template, Transform
from spydra.domain.enums import PageKind, ProposedBy, RuleName, TransformName
from spydra.domain.ids import DomainId, TemplateId

# Lowest id first when several active templates match one URL. Spec 001 §1
# only forbids two active templates with the same pattern, so overlapping
# patterns are legal and something has to pick; the oldest is the least
# surprising. Raised in `.tasks/feat-1.13-worker.md`.
_ACTIVE = sa.text(
    """
SELECT id, domain_id, name, url_pattern, page_kind, version, is_active,
       discovery, extraction, proposed_by, approved_at
FROM crawl.templates
WHERE domain_id = :domain_id AND is_active
ORDER BY id
"""
)


class PostgresTemplates:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def active_for(self, domain_id: DomainId) -> list[Template]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_ACTIVE, {"domain_id": int(domain_id)})).mappings().all()
        return [template_from_row(dict(row)) for row in rows]


def matching(templates: Sequence[Template], url_path: str) -> Template | None:
    """The first template whose `url_pattern` matches (spec 001 §1: a regex
    over path + query)."""
    for template in templates:
        if re.search(template.url_pattern, url_path):
            return template
    return None


def template_from_row(row: Mapping[str, Any]) -> Template:
    re.compile(row["url_pattern"])
    return Template(
        id=TemplateId(row["id"]),
        domain_id=DomainId(row["domain_id"]),
        name=row["name"],
        url_pattern=row["url_pattern"],
        page_kind=PageKind(row["page_kind"]),
        version=row["version"],
        is_active=row["is_active"],
        discovery=discovery_from_json(row["discovery"] or {}),
        extraction=extraction_from_json(row["extraction"] or {}),
        proposed_by=ProposedBy(row["proposed_by"]),
        approved_at=row["approved_at"],
    )


def extraction_from_json(raw: Mapping[str, Any]) -> dict[str, FieldRule]:
    return {name: _field_rule(spec) for name, spec in raw.items()}


def extraction_to_json(extraction: Mapping[str, FieldRule]) -> dict[str, Any]:
    """The inverse, for `1.14`'s loader. `required` is never written."""
    return {name: _field_rule_json(rule) for name, rule in extraction.items()}


def discovery_from_json(raw: Mapping[str, Any]) -> DiscoveryRules:
    return DiscoveryRules(
        next_page=raw.get("next_page"),
        product_links=raw.get("product_links"),
        subcategory_links=raw.get("subcategory_links"),
        allow_patterns=tuple(raw.get("allow_patterns", ())),
        deny_patterns=tuple(raw.get("deny_patterns", ())),
    )


def discovery_to_json(rules: DiscoveryRules) -> dict[str, Any]:
    out: dict[str, Any] = {
        "next_page": rules.next_page,
        "product_links": rules.product_links,
        "subcategory_links": rules.subcategory_links,
        "allow_patterns": list(rules.allow_patterns),
        "deny_patterns": list(rules.deny_patterns),
    }
    return {k: v for k, v in out.items() if v not in (None, [])}


def _field_rule(spec: Mapping[str, Any]) -> FieldRule:
    return FieldRule(
        selector=spec["selector"],
        attr=spec.get("attr", "text"),
        many=bool(spec.get("many", False)),
        transform=tuple(_transform(step) for step in spec.get("transform", ())),
        validation=tuple(_rule(step) for step in spec.get("validation", ())),
        fallback=spec.get("fallback"),
    )


def _field_rule_json(rule: FieldRule) -> dict[str, Any]:
    out: dict[str, Any] = {"selector": rule.selector, "attr": rule.attr, "many": rule.many}
    if rule.transform:
        out["transform"] = [
            {"name": t.name.value, "args": list(t.args)} if t.args else t.name.value
            for t in rule.transform
        ]
    if rule.validation:
        out["validation"] = [
            {"name": r.name.value, "arg": r.arg} if r.arg is not None else r.name.value
            for r in rule.validation
        ]
    if rule.fallback:
        out["fallback"] = rule.fallback
    return out


def _transform(step: str | Mapping[str, Any]) -> Transform:
    if isinstance(step, str):
        return Transform(TransformName(step))
    return Transform(TransformName(step["name"]), tuple(str(a) for a in step.get("args", ())))


def _rule(step: str | Mapping[str, Any]) -> Rule:
    if isinstance(step, str):
        return Rule(RuleName(step))
    return Rule(RuleName(step["name"]), step.get("arg"))
