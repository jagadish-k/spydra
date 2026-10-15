# Gate placeholder: pytest exits 5 with no tests and mypy exits 2 with no
# .py files, so the empty backend would break `make test-api` and `lint-api`
# the moment backend/pyproject.toml exists (BUILD_PLAN 0.2's skip guards key
# on it). Real tests arrive from BUILD_PLAN 0.15 and replace this.


def test_gate_placeholder() -> None:
    assert True
