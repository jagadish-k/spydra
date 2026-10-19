# docs/adr-0027-no-required-fields

**Task:** the operator's global no-required-fields instruction (2026-10-18) ·
**Spec:** specs/001-domain-model.md §3, specs/003-extraction.md §2–3 §5,
specs/012-render-sidecar.md §4, TESTING.md §2 ·
**ADR written by this slice:** 0027

Rule 1: the instruction changes spec 003's stated behaviour, so the ADR comes
before any code. No code here.

Branched from `feat/1.1-1.2-schema-and-domain`, not from `develop`, so the ADR
index stays contiguous — 0026 lives on that branch and two branches appending
to the same table is the conflict ADR-0022 §5 exists to prevent. Merge the
foundation branch first.

## Files this slice owns

- `docs/adr/0027-no-required-fields.md` (new), `docs/adr/README.md` (index row)
- `docs/specs/001-domain-model.md` (§3 only), `docs/specs/003-extraction.md`
  (§2, §3, §5), `docs/specs/012-render-sidecar.md` (§4)
- `docs/TESTING.md` (§2), `docs/BUILD_PLAN.md` (the `1.12` line only)
- `.tasks/docs-adr-0027-no-required-fields.md` (this file)

No code, no schema change, no migration. `FieldRule.required` is deliberately
**left in place** in `spydra/domain/entities.py` and in the
`templates.extraction` JSONB.

## Acceptance

- [x] The ADR exists and is written **before** any edit that depends on it
- [x] Every document that defined behaviour in terms of required fields is
      amended, and each amendment points at the ADR
- [ ] The loader rejects `required: true` — **BUILD_PLAN 1.12**, not here
- [ ] `empty_extraction` is one predicate with three call sites —
      **BUILD_PLAN 1.9/1.10**, not here

## Why this was not a one-line YAML change

The operator's first framing was per-domain: do not mark `price` required on
Active Motif. Taken literally that is a config edit and no ADR. Two things
made it a decision instead:

1. **Two mechanisms were defined on requiredness, and one of them is the
   detector for the failure this project exists to catch.** The 20% →
   `broken` threshold counted "failures"; with nothing required it would have
   counted nothing and never fired, so a site redesign would quietly fill the
   dataset with empty observations. Re-basing it on the `empty_extraction`
   rate keeps it as sharp.
2. **`auto` render mode was also defined on required fields** — in spec 001
   §3 *and* spec 012 §4. With no required fields its retry condition can
   never be true, so `auto` would have silently degraded to `static`, on a
   target list where all three domains need rendering. Found while reading
   spec 012 for the sidecar work, not while writing the ADR; it is the kind
   of consequence a config edit would have shipped silently.

## Open questions

- **The coarseness is a real hole, stated as a cost rather than patched.** A
  redesign that breaks most but not all fields on every page yields no
  `empty_extraction` and will not trip `broken`. The honest mitigation is the
  per-field diff in the phase-5 reports. If it bites, `soft_required` —
  record loudly, never halt — is the shape the fix should take, and it earns
  its own ADR then.
- **`strategy = static_fallback`** (TESTING.md §2, ADR-0016) is still not a
  documented value of `page_observations.strategy`, whose spec 001 §1 comment
  lists `'structured' | 'selector' | 'llm'`. Unchanged by this ADR and still
  open; it belongs to whoever implements the `auto` path in 1.8.

## Handoff log

- planner — read specs 001/003/012 and TESTING §2 for every definition that
  rested on `required`; found four documents and the `auto` collision. ADR
  written first, then the six amendments, each cross-referenced.
- reviewer — not run. The parts worth a second reader are the re-based
  `broken` threshold (it must not be weaker than what it replaced) and the
  stated cost of per-field blindness.
- integrator — docs only; `make check` does not read these files. The claims
  are the review surface.
