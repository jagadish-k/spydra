"""Structural guards on the migration chain (spec 001 §5).

The real proof that a migration reverses is running it: `make migrate-down`
is in the test suite's remit per spec 001 §5, and CI runs `migrate-down`
followed by `migrate` again (phase-0 audit F4 added that step). This file
does **not** duplicate that — a suite test that ran `downgrade base` would
drop the schema out from under every other test in the session.

What it does catch is the cheap version of the same mistake: a migration that
ships with an empty `downgrade()` and therefore passes a one-way CI step
while being irreversible in fact.
"""

import ast
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"

# The chain's first revision is empty on purpose: it pins the chain so every
# environment can be proven at head, and there is nothing to reverse.
BASELINE = "2ff8b22bee8f"


def revision_files() -> list[Path]:
    files = sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("_"))
    assert files, "no migrations found"
    return files


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no {name}() in the module")


def _is_trivial(fn: ast.FunctionDef) -> bool:
    """True if the body is nothing but docstrings, `pass` and `...`."""
    for stmt in fn.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # a docstring, or a bare `...`
        return False
    return True


@pytest.mark.parametrize("path", revision_files(), ids=lambda p: p.stem)
def test_every_revision_has_upgrade_and_downgrade(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    _function(tree, "upgrade")
    _function(tree, "downgrade")


@pytest.mark.parametrize("path", revision_files(), ids=lambda p: p.stem)
def test_a_revision_that_does_something_also_undoes_it(path: Path) -> None:
    """`make migrate-down` is part of the suite and CI fails an irreversible
    migration (spec 001 §5). An empty downgrade passes both while leaving the
    database one-way, so it is rejected here instead."""
    if path.stem.startswith(BASELINE):
        pytest.skip("the baseline is empty in both directions, on purpose")

    tree = ast.parse(path.read_text(), filename=str(path))
    upgrade_trivial = _is_trivial(_function(tree, "upgrade"))
    downgrade_trivial = _is_trivial(_function(tree, "downgrade"))

    assert upgrade_trivial == downgrade_trivial, (
        f"{path.name}: upgrade and downgrade disagree about whether this "
        "revision does anything. A migration with a body and an empty "
        "downgrade() is irreversible."
    )


# Postgres will not coerce an integer default onto a boolean column, and
# alembic's renderer produces exactly that from sa.true()/sa.false(). It cost
# a failed `make migrate` once; these are the two spellings that fail.
_BOOLEAN_INTEGER_DEFAULTS = ("sa.text(\"0\")", "sa.text('0')", "sa.text(\"1\")", "sa.text('1')")


@pytest.mark.parametrize("path", revision_files(), ids=lambda p: p.stem)
def test_no_boolean_column_defaults_to_an_integer(path: Path) -> None:
    """`DEFAULT 0` on a BOOLEAN column is a hard error in Postgres:
    "column is of type boolean but default expression is of type integer".

    `sa.true()` and `sa.false()` compile correctly through SQLAlchemy but
    render into a migration as `sa.text("1")` and `sa.text("0")`, so a
    metadata-level DDL check passes and the migration still fails. Static,
    so it catches the mistake without a database — which is the whole point,
    because the database is what it otherwise fails against.
    """
    offenders = [
        line.strip()
        for line in path.read_text().splitlines()
        if "sa.Boolean" in line and any(bad in line for bad in _BOOLEAN_INTEGER_DEFAULTS)
    ]
    assert not offenders, (
        f"{path.name}: boolean column(s) defaulting to an integer:\n  "
        + "\n  ".join(offenders)
        + '\n\nUse sa.text("true") / sa.text("false").'
    )


def test_the_chain_is_linear() -> None:
    """One head. A branched chain makes `downgrade -1` ambiguous, and nothing
    in this project needs branching (spec 001 §5)."""
    revisions: dict[str, str | None] = {}
    for path in revision_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        found: dict[str, str | None] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in ("revision", "down_revision") and isinstance(
                    node.value, ast.Constant
                ):
                    literal = node.value.value
                    found[node.target.id] = None if literal is None else str(literal)
        assert "revision" in found, f"{path.name}: no revision identifier"
        revisions[str(found["revision"])] = found.get("down_revision")

    parents = [down for down in revisions.values() if down is not None]
    assert len(parents) == len(set(parents)), f"two revisions share a parent: {parents}"

    heads = set(revisions) - set(parents)
    assert len(heads) == 1, f"expected one head, found {sorted(heads)}"

    roots = [rev for rev, down in revisions.items() if down is None]
    assert roots == [BASELINE], f"expected {BASELINE} as the only root, found {roots}"
