"""Test package.

Exists so `tests.fixtures.server` resolves to exactly one module name.
Without it mypy finds that file twice — once as top-level `server`, once as
`tests.fixtures.server` — and refuses to check anything. `server.py` is the
first module in this tree that another test imports, which is why no
`__init__.py` was needed before BUILD_PLAN 1.4.
"""
