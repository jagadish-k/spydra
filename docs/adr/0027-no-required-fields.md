# 0027 — No field is ever required; emptiness is the only failure signal

**Status:** Accepted · 2026-10-18
**Amends:** [spec 001](../specs/001-domain-model.md) §3,
[spec 003](../specs/003-extraction.md) §3 and §5,
[spec 012](../specs/012-render-sidecar.md) §4,
[`TESTING.md`](../TESTING.md) §2
**Relates to:** [ADR-0007](0007-append-only-observations.md) (append-only
observations), [ADR-0016](0016-render-sidecar.md) (`auto` render mode)

## Context

Spec 003 §3 made per-field validation the routing mechanism: a **required**
field failing sends its page to `unknown_pages` with reason
`validation_failed`, and failures past 20% of a run move the domain to
`broken`.

The first three real targets (`docs/TARGETS.md`) break that model on contact.
Active Motif publishes no prices at all — life-sciences catalogues quote
rather than price. A template marking `price` required would send every
product page to the review inbox and then halt the domain on the first run,
reporting a redesign where nothing had changed. The operator's instruction is
to gather whatever resolves and triage the rest by hand.

The appealing move is "do not mark price required on that domain". It is also
the wrong move, because it leaves the decision in a per-domain YAML file where
getting it wrong is silent, and because **the same instinct that marks a
field required is the one that halts a healthy domain.** Once there is a
review inbox and a `validation` record per observation, requiredness buys
nothing that reading them does not.

The real risk in removing it is the opposite one, and it is the reason this
needs a record: **two mechanisms are defined in terms of required fields, and
removing the concept naively disables both.** One of them is the detector for
the failure this entire project exists to catch.

## Decision

**No field may be marked `required`, on any domain.**

- `FieldRule.required` stays in the type and in the `templates.extraction`
  JSONB. Removing it would touch spec 001 §1's schema and ADR-0006's
  immutable prior template versions for no gain. It becomes **inert**, and
  inertness is enforced rather than trusted: the YAML loader (BUILD_PLAN
  1.12) **rejects** `required: true` rather than ignoring it, the authoring
  pipeline (ADR-0019) never sets it, and a test asserts no active template
  carries it.
- **Validation still runs on every field, and still records.** Spec 003 §3's
  "validation never raises — it records" is unchanged, and
  `page_observations.validation` is unchanged. A failing selector is still
  visible per field, per observation. What changes is that a failure no
  longer *routes* or *halts*; it is evidence for a human, not a control flow.

### The two mechanisms that had to be re-based

**1. `unknown_pages` routing.** `validation_failed` no longer fires. The
reason that matters is **`empty_extraction`** — every field resolving to
nothing on a 200 — which spec 003 §3 already calls the redesign signature and
which is what the operator actually needs in the inbox.

**2. The `broken` threshold.** It was "failures exceeding 20% of a domain's
pages". Re-based on the **`empty_extraction` rate**: pages that returned 200
and yielded nothing, over pages crawled in the run. Above 20%, the domain
moves to `broken` and crawling stops for it mid-run, exactly as before.

That second one is load-bearing. Left attached to per-field validation it
would simply never fire, and a site redesign would quietly fill the dataset
with empty observations — "the system's most important failure mode: it
produces no error and no crash, just wrong data" (spec 003 §3). The detector
is not weakened by this ADR; it is pointed at the signal that survives.

**3. `auto` render mode, which was also defined on required fields.** Spec
001 §3 and spec 012 §4 both said `auto` retries through the browser when "the
template's required fields fail to resolve on a 200". With no required fields
that condition can never be true, and `auto` would silently become `static` —
on a target list where all three domains need rendering. Re-based on the same
predicate: `auto` retries through the sidecar when the static fetch returned
200 and the extraction yielded **nothing usable**.

### One predicate, three consumers

```
empty_extraction(fields) ⇔ http_status == 200 and no field resolved to a
                           non-empty value
```

It decides the `auto` fallback, the `unknown_pages` reason, and the `broken`
threshold. One function in `extraction/validation.py`, three call sites. They
cannot disagree about what "nothing came back" means, which they could while
each owned its own notion of failure.

## Consequences

- **A domain with partially-missing data stays `active` and keeps crawling.**
  Active Motif reports empty price fields run after run; the operator sees
  them in the `validation` record and decides. That is the intended outcome
  and the reason for the change.
- **The review inbox gets quieter and more meaningful.** One reason for a
  page landing there, and it means something specific.
- **`TESTING.md` §2 changes, and not by deletion.** "Required field failing
  validation routes to `unknown_pages`" is replaced by its inverse — a
  failing field is recorded and does **not** route or halt — and the
  21%/19% test is re-based on the empty-extraction rate. Both remain
  non-negotiable; they now assert the behaviour the system actually has.
- **Cost: a genuinely broken selector on one field is now invisible until
  someone looks.** Before, marking that field required would surface it
  immediately. The mitigation is that it was never reliable — the operator
  had to guess requiredness at onboarding, before seeing the site's real
  shape — and the `validation` JSONB plus the phase-5 reports are where it
  belongs. Accepted deliberately: a false halt costs a domain, a missed
  single-field failure costs one column until the next report.
- **Cost: the 20% threshold is now coarser.** A redesign that breaks most but
  not all fields on every page yields no `empty_extraction` at all and will
  not trip `broken`. That is a real hole. It is left open rather than patched
  with a second threshold nobody can tune, and the honest mitigation is the
  per-field diff in the phase-5 reports (ADR-0007's `price_history` view is
  the same shape of answer).

## Alternatives considered

**Per-domain configuration — just do not mark price required on Active
Motif.** Rejected as the mechanism, though it is what the operator first
described. It leaves a decision that halts crawling in a YAML file where
getting it wrong is silent and per-domain, and it keeps three mechanisms
hanging off a flag whose correct value is unknowable at onboarding.

**Keep `required` and lower the `broken` threshold.** Rejected: it tunes a
number instead of fixing what the number counts, and a domain that legitimately
lacks a field still halts, just later.

**A `soft_required` level — record loudly, never halt.** Rejected as
premature. It is `required: false` plus a report, and the reports arrive in
phase 5. If the per-field blindness above turns out to bite, this is the shape
the fix should take, and it earns an ADR then.

**Remove `required` from the schema entirely.** Rejected: it touches spec 001
§1 and prior immutable template versions (ADR-0006) to delete a field that a
loader rejection and a test already neutralise.
