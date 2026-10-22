"""`python -m spydra.load <file.yaml>`: configure domains without a UI.

BUILD_PLAN 1.14. **Scaffolding with a known end date**: `3.2` deletes this once
templates come from the API. So there is deliberately no schema, no validator
and no inheritance, and nothing anyone could grow attached to. The file is the
operator's approval: what it says is written as active, and a run is started
over its seed URLs.

```yaml
domains:
  - host: vantage-abrasives.test     # may carry a port
    scheme: https                    # for seed paths; default https
    render_mode: static              # static | rendered | auto
    crawl_delay_ms: 2000             # the operator's floor (spec 002 §4)
    respect_robots: true
    templates:
      - name: product
        url_pattern: "/catalog/.+/.+"
        page_kind: product
        extraction:                  # spec 013 §2's FieldCandidate
          title: { selector: ".product__title", transform: [trim] }
    seeds: [/catalog/abrasives/discs/rfd-115-060]
```

**The one check it makes is the one it must**: `required: true` anywhere is
refused, naming ADR-0027, and nothing is written. Ignoring it would let an
operator believe a field is enforced when nothing reads the flag. Everything
else is decoded through the same codec the worker reads with, so a template
the worker could not read fails here, before it is written, rather than on
every page of a run.
"""

import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from sqlalchemy.ext.asyncio import create_async_engine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.adapters.postgres.templates import (
    discovery_from_json,
    discovery_to_json,
    extraction_from_json,
    extraction_to_json,
)
from spydra.domain.entities import DiscoveryRules, FieldRule
from spydra.domain.enums import PageKind, RenderMode
from spydra.domain.ids import RunId


class RefusedConfiguration(ValueError):
    """The file asks for something the system will not do."""


@dataclass(frozen=True, slots=True)
class TemplateConfig:
    name: str
    url_pattern: str
    page_kind: PageKind
    extraction: Mapping[str, FieldRule]
    discovery: DiscoveryRules


@dataclass(frozen=True, slots=True)
class DomainConfig:
    host: str
    render_mode: RenderMode
    crawl_delay_ms: int
    respect_robots: bool
    templates: tuple[TemplateConfig, ...]
    seeds: tuple[str, ...]

    def template_rows(self) -> list[dict[str, Any]]:
        """Each template as the JSONB the worker decodes."""
        return [
            {
                "name": t.name,
                "url_pattern": t.url_pattern,
                "page_kind": t.page_kind.value,
                "extraction": extraction_to_json(t.extraction),
                "discovery": discovery_to_json(t.discovery),
            }
            for t in self.templates
        ]


def parse(text: str) -> tuple[DomainConfig, ...]:
    raw = YAML(typ="safe", pure=True).load(text) or {}
    _refuse_required(raw)
    return tuple(_domain(d) for d in raw.get("domains", ()))


async def load(configuration: PostgresConfiguration, text: str) -> RunId:
    """Parse, then write everything and start the run in one transaction."""
    return await configuration.apply(parse(text))


def _refuse_required(node: object, path: str = "") -> None:
    """ADR-0027: no field is ever required. Walks the whole document, not just
    `extraction`, so a `required` the operator put one level off still fails
    loudly rather than being silently ignored."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            # Anything but a literal `false`. YAML 1.2 reads `yes`, `on` and
            # `"true"` as strings, which would slip past an `is True` test and
            # leave an operator believing a field is enforced when nothing
            # reads the flag: the exact case ADR-0027 names.
            if key == "required" and value is not False:
                raise RefusedConfiguration(
                    f"{here}: `required: {value}` is refused. No field is ever required "
                    "(ADR-0027): a field that fails is recorded in the observation's "
                    "validation, and only an empty extraction routes or halts. Remove "
                    "the key."
                )
            _refuse_required(value, here)
    elif isinstance(node, Sequence) and not isinstance(node, str):
        for i, value in enumerate(node):
            _refuse_required(value, f"{path}[{i}]")


def _domain(raw: Mapping[str, Any]) -> DomainConfig:
    host = str(raw["host"])
    scheme = str(raw.get("scheme", "https"))
    return DomainConfig(
        host=host,
        render_mode=RenderMode(raw.get("render_mode", RenderMode.STATIC.value)),
        crawl_delay_ms=int(raw.get("crawl_delay_ms", 2000)),
        respect_robots=bool(raw.get("respect_robots", True)),
        templates=tuple(_template(t) for t in raw.get("templates", ())),
        seeds=tuple(_seed(str(s), scheme, host) for s in raw.get("seeds", ())),
    )


def _template(raw: Mapping[str, Any]) -> TemplateConfig:
    return TemplateConfig(
        name=str(raw["name"]),
        url_pattern=str(raw["url_pattern"]),
        page_kind=PageKind(raw.get("page_kind", PageKind.PRODUCT.value)),
        extraction=extraction_from_json(raw.get("extraction", {})),
        discovery=discovery_from_json(raw.get("discovery", {})),
    )


def _seed(seed: str, scheme: str, host: str) -> str:
    return seed if "://" in seed else f"{scheme}://{host}{seed}"


async def main(path: str) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        with open(path, encoding="utf-8") as f:
            run_id = await load(PostgresConfiguration(engine), f.read())
    finally:
        await engine.dispose()
    print(f"run {int(run_id)} started from {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m spydra.load <file.yaml>")
    try:
        asyncio.run(main(sys.argv[1]))
    except RefusedConfiguration as refused:
        sys.exit(f"refused: {refused}")
