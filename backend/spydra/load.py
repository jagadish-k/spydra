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
from urllib.parse import urlsplit

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
from spydra.domain.errors import RefusedConfiguration
from spydra.domain.ids import RunId

__all__ = ["DomainConfig", "RefusedConfiguration", "TemplateConfig", "load", "parse"]


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
    outcome = await configuration.apply(parse(text))
    assert outcome.run_id is not None  # skip_refused unset: apply starts the run or raises
    return outcome.run_id


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
        respect_robots=_bool(raw, "respect_robots", True, host),
        templates=tuple(_template(t) for t in raw.get("templates", ())),
        seeds=tuple(_seed(str(s), scheme, host) for s in raw.get("seeds", ())),
    )


def _template(raw: Mapping[str, Any]) -> TemplateConfig:
    extraction = raw.get("extraction", {})
    for field, spec in extraction.items():
        if isinstance(spec, Mapping):
            _bool(spec, "many", False, f"{raw.get('name')}.{field}")
    return TemplateConfig(
        name=str(raw["name"]),
        url_pattern=str(raw["url_pattern"]),
        page_kind=PageKind(raw.get("page_kind", PageKind.PRODUCT.value)),
        extraction=extraction_from_json(extraction),
        discovery=discovery_from_json(_discovery(raw)),
    )


def _discovery(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """A template's discovery rules, refusing what would be silently dropped.

    `max_depth` lives on the domain (spec 001 §1, spec 004 §1); a template
    copy of it would load, be ignored, and crawl to the domain's depth while
    the file says otherwise. Refused, as `required` is.
    """
    discovery = raw.get("discovery", {})
    if isinstance(discovery, Mapping) and "max_depth" in discovery:
        raise RefusedConfiguration(
            f"template {raw.get('name')!r}: discovery.max_depth is not a template "
            "setting; it is per domain (spec 001 §1, spec 004 §1)"
        )
    return discovery if isinstance(discovery, Mapping) else {}


def _seed(seed: str, scheme: str, host: str) -> str:
    """A path is resolved against the domain. A full URL must BE the domain:
    the worker reads robots.txt, the delay and the pause state of the seed's
    domain row, so a seed on another host would be fetched under someone
    else's politeness, past that host's own robots and any pause it is under."""
    if "://" not in seed:
        return f"{scheme}://{host}{seed}"
    if urlsplit(seed).netloc.lower() != host.lower():
        raise RefusedConfiguration(
            f"seed {seed} is not on {host}. Each seed is crawled under its domain's "
            "robots.txt and politeness, so it belongs under the domain it is on."
        )
    return seed


def _bool(raw: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    """A real YAML boolean, or the default. YAML 1.2 reads `no` and `off` as
    strings, and `bool("no")` is True, so `many: no` silently meant many
    (found in review)."""
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise RefusedConfiguration(f"{where}.{key}: {value!r} is not true or false")
    return value


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
