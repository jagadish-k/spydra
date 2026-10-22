# 0037 — An empty extraction is one with nothing substantive in it

**Status:** Accepted · 2026-10-22
**Amends:** [ADR-0027](0027-no-required-fields.md) (the predicate's
definition), [ADR-0030](0030-empty-needs-a-prior.md) (how "a prior non-empty
observation" is read), [spec 003](../specs/003-extraction.md) §3
**Relates to:** [ADR-0033](0033-current-state-skips-lightweight-rows.md)
("nothing comparable" has no hash)

## Context

ADR-0027 defined one predicate with three callers:

```
empty_extraction(fields) ⇔ http_status == 200 and no field resolved to a
                           non-empty value
```

An SEO plugin's `schema.org/Product` that carries only an `image` defeats it.
When the approved template comes back empty — a redesign — the chain still
returns the stub's `{images: [...]}`, because an image URL is "a field that
resolved". The page is therefore not an empty extraction. It never reaches the
inbox and never counts toward ADR-0030's threshold. A domain whose SEO plugin
emits such stubs can be redesigned and keep writing NULL-title rows run after
run without ever tripping `broken`. That is the failure ADR-0027 exists to
catch (measured: `.tasks/fix-2.0-phase1-decisions.md`).

The three callers had also already drifted apart. 1.13's `auto` fallback
(caller 1) needed the stub to get its browser retry, so it tests
`not is_substantive(fields)` instead of the predicate. Callers 2 and 3 (the
inbox reason, the threshold) test `empty_extraction`. That made two
definitions of "nothing usable" in production.

`is_substantive` comes from 1.11: something survives the content hash's
normalisation (spec 003 §4). Asset URLs do not survive it, and nor does the
price composite's `raw` evidence.

## Decision

**The predicate itself changes. The writer does not compute a second
verdict.**

```
empty_extraction(fields) ⇔ http_status == 200 and not is_substantive(fields)
```

- All three callers call this one function again, the `auto` fallback
  included.
- The chain no longer uses the predicate to decide what to keep. It passes
  over a rung that resolved nothing at all (`is_blank`), and keeps the first
  non-blank, non-substantive result as its fallback, as before. So the
  stub's images still reach `asset_queue` even though the page is an empty
  extraction. `is_blank` is not a verdict; it only answers "is there anything
  to carry".
- **ADR-0030's prior is read from the hash, not the column.** "An earlier
  observation whose extraction was non-empty" becomes
  `prior.content_hash IS NOT NULL`. The hash is NULL exactly when nothing
  substantive was extracted (ADR-0033). Rows written before this ADR say
  `empty_extraction = false` for an image-only page, and observations are
  never updated (ADR-0007). So the hash is the column that answers the
  question as this ADR asks it, for every row, old or new.

### Why not a second verdict in the writer

The alternative was to leave `empty_extraction` as ADR-0027 wrote it, and
have the writer compute "a template was consulted, and nothing came back
substantive" for the inbox and the threshold. ADR-0027's "one predicate, three
callers" is the argument against it, and the argument holds:

- It makes **three** definitions of "nothing usable": the predicate,
  `auto`'s `not is_substantive`, and the writer's verdict.
- The observation row would say `empty_extraction = false` on a page the
  inbox files under the reason `empty_extraction`.
- The threshold query reads the column, so it would need a second column or
  its own re-derivation in SQL. A fourth copy.

Changing the predicate makes ADR-0027's sentence true again, at the cost of
widening what "empty" means.

### "A template was consulted" is not part of the predicate

It does not need to be:

- A page with no template is still `no_template` (it outranks
  `empty_extraction`), and is still outside the threshold (ADR-0027 §3).
- The chain tries every rung until one is substantive. So on a page with a
  template and a non-substantive result, the template was always consulted.

## Consequences

- An image-only stub over a broken template is now an empty extraction. It
  opens an inbox row, counts toward the threshold once the page has worked
  before, and moves a first run to `awaiting_approval` past 20%. Its images
  are still enqueued.
- `empty_extraction` and "not substantive" can no longer disagree, so
  `unchanged` (which needs a hash) and `empty_extraction` remain mutually
  exclusive.
- A prior row with a non-200 status and nothing in it no longer counts as
  "once worked". Before, `NOT empty_extraction` was true for every non-200
  row, so a page that 404'd last run and came back empty this run counted as
  a regression.
- **Cost: a template whose only fields are asset URLs, or other URL-valued
  data, yields `empty_extraction` on every page.** No template does this today.
  The authoring pipeline (phase 3) should warn when a template has no field
  that survives normalisation.
- **Cost: a page whose only resolved field is a hollow price (`raw` only,
  e.g. "POA")** is also empty now. It always was non-substantive, and it was
  already hashed as nothing (ADR-0033).
- **An AUTO page with an image-only stub, crawled with `render` down,** now
  records `static_fallback` with `empty_extraction = true`, and once it has a
  hashed prior it counts as a regression. Before, the stub made such pages
  immune. A JS page with no stub was already in that position, so this
  widens a known exposure rather than creating one.
- **Pages with a non-200 status are unchanged.** There the chain still
  returns a rung's blank result, so the observation keeps naming the rung
  that ran.

## Alternatives considered

- **A second verdict computed by the writer.** Rejected above.
- **Do nothing, and rely on the phase-5 per-field diff.** Rejected. That
  report would surface the problem a run late, and only if someone reads it.
  The threshold is the mechanism meant to stop the run.
- **Strip asset fields from the extraction before the predicate.** This is
  the same thing as `is_substantive`, but it would add a second definition of
  "asset", next to the hasher's.
