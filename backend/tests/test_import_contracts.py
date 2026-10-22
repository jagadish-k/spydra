"""The domain→adapters import contract (BUILD_PLAN 0.8, AGENTS.md § Conventions).

import-linter cannot run here: its engine (grimp) publishes no cp315 manylinux
aarch64 wheels (see backend/pyproject.toml note), and a contract that only
warns does not gate. This stdlib-AST walk blocks instead of warning.

`spydra/domain` is pure: no I/O, no adapter knowledge. It may import stdlib,
typing and its own submodules. It may not import anything outside itself
except through the ports it defines — which live in spydra.ports, never in
adapters.
"""

import ast
from pathlib import Path

import pytest

_DOMAIN = Path(__file__).resolve().parent.parent / "spydra" / "domain"

# The contract, as one list. Add a prefix here when a new spydra subtree must
# stay invisible to the domain.
FORBIDDEN_PREFIXES = (
    "spydra.adapters",  # domain never knows how work is performed (AGENTS.md)
    "spydra.api",  # HTTP is an edge concern, not a domain one
    "spydra.extraction",
    "spydra.observations",  # 1.11: the write path is above the domain, not in it
    "spydra.scheduler",
    "spydra.worker",
)

# Any relative import of level >= 2 escapes spydra.domain and reaches the
# package root, where the prefixes above live (e.g. `from ..adapters import`).
_MAX_RELATIVE_LEVEL = 1


def _absolute_imports(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # `from spydra import adapters` must resolve to spydra.adapters
            found.extend((node.lineno, f"{node.module}.{alias.name}") for alias in node.names)
    return found


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    problems = []
    for lineno, target in _absolute_imports(tree):
        if target == "spydra" or any(
            target == p or target.startswith(p + ".") for p in FORBIDDEN_PREFIXES
        ):
            problems.append(f"{path}:{lineno}: import {target!r} is forbidden in domain")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > _MAX_RELATIVE_LEVEL:
            problems.append(
                f"{path}:{node.lineno}: relative import escapes spydra.domain "
                f"(level {node.level} > {_MAX_RELATIVE_LEVEL})"
            )
    return problems


def test_domain_imports_nothing_forbidden() -> None:
    if not _DOMAIN.is_dir():
        pytest.skip("spydra/domain does not exist yet — contract activates when it does")
    files = sorted(_DOMAIN.rglob("*.py"))
    problems = [p for f in files for p in _violations(f)]
    assert not problems, "\n".join(problems)
