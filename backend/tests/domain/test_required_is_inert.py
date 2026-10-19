"""`FieldRule.required` is inert, and that is enforced rather than trusted.

ADR-0027 § Decision: `required` "stays in the type and in the
`templates.extraction` JSONB ... It becomes **inert**, and inertness is
enforced rather than trusted."

This is the enforcement. A stdlib AST walk over `spydra/`, in the spirit of
task 0.8's import contract: a lint would warn where this blocks.

What it is protecting. The branch that introduced ADR-0027 also shipped
`Template.required_fields`, a tested and documented property that computed
precisely the routing set the ADR had just removed, with a docstring citing
spec 003 §3 as its authority. Found by a reviewer, not by a test. The failure
it would have caused is the one ADR-0027 names in its own §3: whoever writes
1.9 or 1.10 finds a ready-made API for re-attaching the `broken` threshold to
per-field validation, where it never fires and a site redesign fills the
dataset silently.
"""

import ast
from pathlib import Path

import pytest

SPYDRA = Path(__file__).resolve().parents[2] / "spydra"

# The one place the attribute may be named: its own declaration.
DECLARATION = "domain/entities.py"


def _reads_of_required(path: Path) -> list[str]:
    """Attribute reads (`x.required`) and keyword uses (`required=...`)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "required":
            hits.append(f"{path}:{node.lineno}: reads `.required`")
        elif isinstance(node, ast.keyword) and node.arg == "required":
            hits.append(f"{path}:{node.lineno}: passes `required=`")
    return hits


def source_files() -> list[Path]:
    files = sorted(SPYDRA.rglob("*.py"))
    assert files, "no sources under spydra/ — has the package moved?"
    return files


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_no_production_code_reads_required(path: Path) -> None:
    if path.as_posix().endswith(DECLARATION):
        pytest.skip(f"{DECLARATION} declares the field; the annotation is not a read")

    hits = _reads_of_required(path)
    assert not hits, (
        "`FieldRule.required` is inert (ADR-0027) and nothing may read it:\n  "
        + "\n  ".join(hits)
        + "\n\nThe signal is emptiness — a 200 from which nothing resolved. It "
        "decides the unknown_pages reason, the broken threshold and the `auto` "
        "fallback, and it lives in extraction/validation.py."
    )


def test_the_declaration_is_still_there() -> None:
    """Inert, not deleted.

    ADR-0027 kept the field deliberately: removing it would touch spec 001
    §1's schema and ADR-0006's immutable prior template versions. If someone
    deletes it, that is a schema decision and wants its own record — so this
    fails rather than letting it happen quietly.
    """
    from spydra.domain import FieldRule

    assert "required" in {f.name for f in __import__("dataclasses").fields(FieldRule)}
    assert FieldRule(selector=".x").required is False
