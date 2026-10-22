"""The YAML loader's parsing half (BUILD_PLAN 1.14), with no database.

Two things are held here:

- **ADR-0027's one check.** `required: true` anywhere in the document is
  refused with a message naming the ADR. "Anywhere" is the point: a
  `required` put one level off is the operator believing a field is enforced,
  and nothing reads the flag.
- **The committed exit files still mean what the exit run needs.** The phase
  1 exit (`make phase1-exit`) needs the live stack, so drift between
  `phase1/*.yaml` and the fixture pages would otherwise only show up there.
  Here the files' own templates go through the real chain against the same
  `1.4` pages the `fixtures` service serves.
"""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from spydra.domain.entities import FieldRule, Rule, Template, Transform
from spydra.domain.enums import PageKind, ProposedBy, RenderMode, RuleName, TransformName
from spydra.domain.ids import DomainId, TemplateId
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.extraction.hashing import is_substantive
from spydra.load import DomainConfig, RefusedConfiguration, TemplateConfig, parse
from tests.extraction.pages import page

PHASE1 = Path(__file__).resolve().parent / "fixtures" / "phase1"


# ---------------------------------------------------------------------------
# ADR-0027: `required: true` is refused, wherever it is
# ---------------------------------------------------------------------------

_ON_A_FIELD = """
domains:
  - host: a.test
    templates:
      - name: product
        url_pattern: "/p/.+"
        extraction:
          title: { selector: "h1", required: true }
"""

# One level off: on the template, not the field.
_ON_THE_TEMPLATE = """
domains:
  - host: a.test
    templates:
      - name: product
        url_pattern: "/p/.+"
        required: true
        extraction:
          title: { selector: "h1" }
"""

# On the domain.
_ON_THE_DOMAIN = """
domains:
  - host: a.test
    required: true
    templates: []
"""

# At the top of the document.
_AT_THE_TOP = """
required: true
domains: []
"""

# Inside a list: a transform step written as a mapping.
_INSIDE_A_TRANSFORM_LIST = """
domains:
  - host: a.test
    templates:
      - name: product
        url_pattern: "/p/.+"
        extraction:
          title:
            selector: "h1"
            transform: [{ name: trim, required: true }]
"""

# Inside a list of lists, on the second domain: a refusal must not depend on
# the first domain being the one that carries it.
_NESTED_LISTS_SECOND_DOMAIN = """
domains:
  - host: a.test
    templates: []
  - host: b.test
    seeds:
      - - { path: /x, required: true }
"""


@pytest.mark.parametrize(
    "text",
    [
        _ON_A_FIELD,
        _ON_THE_TEMPLATE,
        _ON_THE_DOMAIN,
        _AT_THE_TOP,
        _INSIDE_A_TRANSFORM_LIST,
        _NESTED_LISTS_SECOND_DOMAIN,
    ],
    ids=["field", "template", "domain", "top", "transform-list", "nested-list-2nd-domain"],
)
def test_required_true_anywhere_is_refused_naming_adr_0027(text: str) -> None:
    with pytest.raises(RefusedConfiguration, match="ADR-0027"):
        parse(text)


@pytest.mark.parametrize(
    "spelling",
    # The last four are not booleans in YAML 1.2, so an `is True` check let
    # them through while the codec dropped the key: an operator believing a
    # field was enforced (ADR-0027). Only a literal `false` is accepted.
    ["true", "True", "TRUE", "yes", "on", "1", '"true"'],
)
def test_every_yaml_spelling_of_true_is_refused(spelling: str) -> None:
    """YAML 1.2's core schema has three spellings of the boolean; an operator
    who wrote any of them meant the same thing."""
    with pytest.raises(RefusedConfiguration, match="ADR-0027"):
        parse(_ON_A_FIELD.replace("required: true", f"required: {spelling}"))


def test_the_refusal_says_where_the_key_is() -> None:
    """A file of forty templates is no use if the message does not say which."""
    with pytest.raises(RefusedConfiguration) as refused:
        parse(_ON_A_FIELD)

    assert "title" in str(refused.value)


def test_required_false_is_accepted_and_not_carried_into_the_rule() -> None:
    (domain,) = parse(_ON_A_FIELD.replace("required: true", "required: false"))

    (template,) = domain.templates
    assert template.extraction["title"] == FieldRule(selector="h1")
    assert all(
        "required" not in field
        for row in domain.template_rows()
        for field in row["extraction"].values()
    )


# ---------------------------------------------------------------------------
# What a valid file parses to
# ---------------------------------------------------------------------------

_VALID = """
domains:
  - host: shop.test:8099
    scheme: http
    render_mode: auto
    crawl_delay_ms: 5000
    respect_robots: false
    templates:
      - name: product
        url_pattern: "/p/.+"
        page_kind: product
        extraction:
          title: { selector: ".t", transform: [trim], validation: [non_empty] }
          specs:
            selector: ".specs tr"
            many: true
            transform: [{ name: pairs, args: [th, td] }]
            validation: [{ name: min_count, arg: 3 }]
          price:
            selector: ".price"
            fallback: "[itemprop=price]"
    seeds:
      - /p/one
      - https://elsewhere.test/p/two
  - host: plain.test
    seeds: [/p/three]
"""


def test_a_valid_file_parses_to_the_domains_it_describes() -> None:
    shop, plain = parse(_VALID)

    assert shop.host == "shop.test:8099"
    assert shop.render_mode is RenderMode.AUTO
    assert shop.crawl_delay_ms == 5000
    assert shop.respect_robots is False
    (template,) = shop.templates
    assert template.name == "product"
    assert template.url_pattern == "/p/.+"
    assert template.page_kind is PageKind.PRODUCT
    assert template.extraction == {
        "title": FieldRule(
            selector=".t",
            transform=(Transform(TransformName.TRIM),),
            validation=(Rule(RuleName.NON_EMPTY),),
        ),
        "specs": FieldRule(
            selector=".specs tr",
            many=True,
            transform=(Transform(TransformName.PAIRS, ("th", "td")),),
            validation=(Rule(RuleName.MIN_COUNT, 3),),
        ),
        "price": FieldRule(selector=".price", fallback="[itemprop=price]"),
    }
    assert plain.host == "plain.test"


def test_path_seeds_resolve_against_scheme_and_host_and_full_urls_are_kept() -> None:
    shop, plain = parse(_VALID)

    assert shop.seeds == ("http://shop.test:8099/p/one", "https://elsewhere.test/p/two")
    # No scheme given: https.
    assert plain.seeds == ("https://plain.test/p/three",)


@pytest.mark.parametrize(
    "broken",
    [
        _VALID.replace("transform: [trim]", "transform: [titlecase]"),
        _VALID.replace('selector: ".price"\n', ""),
    ],
    ids=["unknown-transform", "missing-selector"],
)
def test_a_template_the_worker_could_not_read_fails_to_parse(broken: str) -> None:
    """Spec 013 §2's codec is the worker's; a template it cannot decode must
    fail here, before anything is written, not on every page of a run."""
    with pytest.raises((ValueError, KeyError)):
        parse(broken)


# ---------------------------------------------------------------------------
# The committed exit files (BUILD_PLAN 1.14's Exit, ADR-0036)
# ---------------------------------------------------------------------------


def _as_template(config: TemplateConfig) -> Template:
    return Template(
        id=TemplateId(1),
        domain_id=DomainId(1),
        name=config.name,
        url_pattern=config.url_pattern,
        page_kind=config.page_kind,
        version=1,
        is_active=True,
        discovery=config.discovery,
        extraction=config.extraction,
        proposed_by=ProposedBy.HUMAN,
    )


def _by_host(domains: tuple[DomainConfig, ...]) -> dict[str, DomainConfig]:
    return {d.host.split(".")[0]: d for d in domains}


def _chain() -> ExtractionChain:
    return ExtractionChain([StructuredStrategy(), SelectorStrategy()])


@pytest.mark.parametrize("name", ["render-up.yaml", "render-down.yaml"])
def test_the_exit_files_parse(name: str) -> None:
    domains = parse((PHASE1 / name).read_text())

    assert domains
    assert all(d.templates and d.seeds for d in domains)


def test_render_up_has_one_domain_per_render_mode() -> None:
    domains = _by_host(parse((PHASE1 / "render-up.yaml").read_text()))

    assert domains["vantage"].render_mode is RenderMode.STATIC
    assert domains["mertens"].render_mode is RenderMode.RENDERED
    assert domains["orbis"].render_mode is RenderMode.AUTO


def test_render_down_keeps_static_and_auto_and_drops_rendered() -> None:
    """With no sidecar a RENDERED domain stalls by design, so the run would
    never complete (the file's own comment)."""
    domains = _by_host(parse((PHASE1 / "render-down.yaml").read_text()))

    assert {mode.render_mode for mode in domains.values()} == {RenderMode.STATIC, RenderMode.AUTO}


@pytest.mark.parametrize("name", ["render-up.yaml", "render-down.yaml"])
async def test_the_exit_vantage_template_extracts_the_static_product(name: str) -> None:
    vantage = _by_host(parse((PHASE1 / name).read_text()))["vantage"]
    (seed,) = vantage.seeds
    (config,) = vantage.templates
    fetched = page("vantage-abrasives/product.html", seed)

    result = await _chain().extract(fetched, _as_template(config))

    assert result.fields["title"] == "Resin Fibre Disc 115mm P60"


@pytest.mark.parametrize(
    ("name", "host"),
    [("render-up.yaml", "mertens"), ("render-up.yaml", "orbis"), ("render-down.yaml", "orbis")],
)
async def test_the_exit_mertens_template_finds_nothing_substantive_in_the_static_html(
    name: str, host: str
) -> None:
    """The JS page's static HTML carries the product only inside a script.
    That emptiness is what sends AUTO to its second chance in the exit run,
    and what makes `static_fallback` the outcome with `render` stopped; a
    template that matched the static HTML would make the exit pass without
    the sidecar ever being exercised."""
    domain = _by_host(parse((PHASE1 / name).read_text()))[host]
    (seed,) = domain.seeds
    (config,) = domain.templates
    fetched = page("mertens/product-rendered.html", seed)

    result = await _chain().extract(fetched, _as_template(config))

    assert not is_substantive(result.fields)
    assert not result.fields.get("title")


@pytest.mark.parametrize(
    ("name", "host"),
    [("render-up.yaml", "vantage"), ("render-up.yaml", "mertens"), ("render-down.yaml", "orbis")],
)
def test_each_exit_template_matches_its_own_seed(name: str, host: str) -> None:
    """A template whose pattern misses its seed leaves the page with no
    template, and the exit would then be measuring `no_template`."""
    domain = _by_host(parse((PHASE1 / name).read_text()))[host]
    (seed,) = domain.seeds
    (config,) = domain.templates

    assert re.search(config.url_pattern, urlsplit(seed).path)
