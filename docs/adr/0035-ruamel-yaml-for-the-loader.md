# 0035 — ruamel.yaml for the YAML template loader

**Status:** Accepted · 2026-10-22
**Relates to:** [ADR-0017](0017-version-policy.md) (the wheel gate),
BUILD_PLAN `1.14`

## Context

BUILD_PLAN `1.14` asks for a YAML template loader so a domain can be
configured without a UI. Python has no YAML in its standard library, so this
is a new runtime dependency, and AGENTS.md requires an ADR for one.

The obvious choice is PyYAML. ADR-0017's gate says to check on PyPI, not in a
failing build, that every compiled dependency publishes a wheel for the
current major. Checked on 2026-10-22: **PyYAML 6.0.3 publishes no cp315 wheel
for any platform**. A source build would need a compiler in the slim image, or
a silent fall back to the pure-Python path that nobody chose.

## Decision

**`ruamel.yaml`** (0.19.1), loaded as `YAML(typ="safe", pure=True)`.

- It ships `py3-none-any`. Its C accelerators are opt-in extras
  (`ruamel.yaml.clib`, `clibz`) that this project does not install, so there
  is nothing for the gate to fail on, on any architecture.
- `typ="safe"` builds plain mappings, sequences and scalars, with no
  arbitrary object construction from tags.

## Consequences

- The loader is scaffolding that BUILD_PLAN `3.2` deletes. When it goes, this
  dependency goes with it unless something else has started to use it.
- ruamel.yaml is slower than libyaml-backed PyYAML. A loader that reads one
  hand-written file per invocation does not care.

## Alternatives considered

- **PyYAML:** refused by the wheel gate, as above.
- **JSON or TOML instead of YAML:** `tomllib` is stdlib. But BUILD_PLAN 1.14
  names YAML, and the phase 1 exit criterion is stated in terms of "a YAML
  template". Changing the format is a plan change, not a library choice.
