# feat/1.10-extraction-chain

**Task:** BUILD_PLAN `1.10` · **Spec:** `specs/003-extraction.md` §1–5
**ADRs:** 0005 (the LLM proposes only), **0027 (no required fields)**,
**0030 (empty needs a prior)**, 0008

**Goal.** The ordered chain with its `structured` and `selector` rungs, the
transform table, and validation that **records and never routes**. This is
also where `empty_extraction` is implemented — one predicate in
`extraction/validation.py` with three callers, which is why it lands before
the observation writes and the worker.

**Spec 003 §3 calls the failure this slice guards against "the system's most
important failure mode: it produces no error and no crash, just wrong data."**
Everything below is shaped by that.

---

## Measured before writing anything

1. **`selectolax` and `extruct` were declared nowhere and installed
   nowhere** — both named in AGENTS.md § Stack and in spec 003 §1–2. Same
   class of defect as `httpx2` before `1.6`, except these were not even
   present. ADR-0017's readiness gate was run **before** adding them rather
   than discovered in a failing build: both resolve on cp315/aarch64, which
   is the architecture that kept import-linter out.
2. **`extruct` pulls `requests` transitively.** A second HTTP client in the
   image, which is what ADR-0028 and ADR-0017 fought about. Nothing imports
   it and the crawl path is httpx2 only; raised below rather than hidden.
3. **`Template.url_pattern` is annotated `str`** while the entity's own
   docstring says it "is a compiled pattern, not a string". Raised below.
4. **The two rungs emitted different shapes for a price** — `structured`
   gave `price_amount` + `price_currency`, `selector` a composite. mypy
   caught it. Unified on one composite, below.

## Decisions

- **One `price` composite, emitted by both rungs.** Spec 003 §2 makes the
  currency a first-class part of a price ("a price without a determinable
  currency is a validation failure, not a guess"), so amount and code have
  to travel together for one rule to check both — and `raw` travels with
  them because spec 003 §3's example record is `{"rule": "currency", "ok":
false, "saw": "POA"}` and `POA` is the only part of that which explains
  anything. `FieldValue` is widened by one alias; `1.11` splits the composite
  into `price_amount` and `price_currency`.
- **`strip_currency` removes only an _unambiguous_ thousands separator.**
  Spec 003 §2 asks it to "remove symbol and thousands separators", and the
  word doing the work is _thousands_: `1,234.56` has two separators so the
  first is thousands, while `1,234` has one and is genuinely ambiguous —
  1234 in English, 1.234 in German. Stripping it would silently pick the
  English reading, a thousandfold error on a real number. So the ambiguous
  case travels on intact and `parse_decimal` refuses it.
- **Nothing in a strategy routes or halts.** A selector that resolves to
  nothing yields `None`, validation records it, and the observation is
  written with whatever else resolved (ADR-0027). The one thing that _is_
  control flow — every field empty on a 200 — lives in one predicate so the
  three consumers ADR-0027 names cannot disagree about it.
- **Rung 2 returns `None` for "no template", not an empty mapping.**
  ADR-0027 §3 excludes no-template pages from the `broken` threshold
  entirely — their reason is `no_template`, a configuration gap rather than a
  redesign. An empty mapping would make an unconfigured domain look like a
  redesigned one.
- **The chain checks `empty_extraction`, not `is None`.** A rung that
  returns a mapping of all-empty values has not extracted anything, and
  stopping there would leave the template unreachable on a page whose JSON-LD
  is present but hollow — a shape that exists, because SEO plugins emit
  skeleton markup.
- **Rung 3 is absent on purpose.** ADR-0005: the model proposes rules during
  onboarding and never runs during a crawl, so a chain that _could_ reach an
  LLM at crawl time would be a defect however well it worked. A test asserts
  the composition.

## Files this slice owns

```
backend/pyproject.toml, backend/uv.lock        (selectolax, extruct, mypy override)
backend/spydra/domain/entities.py              (PriceValue, one alias)
backend/spydra/extraction/transforms.py        (NEW)
backend/spydra/extraction/validation.py        (NEW — the one predicate)
backend/spydra/extraction/chain.py             (NEW — owns the order)
backend/spydra/extraction/strategies/{structured,selector}.py (NEW)
backend/tests/extraction/test_{transforms,validation,chain}.py (NEW)
docs/BUILD_PLAN.md                             (tick 1.10 — in the PR)
```

## Acceptance (spec 003 §5)

- [x] **G1** A JSON-LD page extracts via `structured` **without a template**.
- [x] **G2** The same page with the JSON-LD removed falls through.
- [x] **G3** A field failing validation is recorded, the observation is
      written, and nothing routes or halts (ADR-0027).
- [x] **G4** A price of **"POA"** is a validation failure, not `0.00`, and
      the record says `saw: "POA"`.
- [x] **G5** The redesigned fixture produces `empty_extraction`.
- [x] **G6** The soft 404 also does — the predicate cannot tell them apart,
      which is the point; the prior observation is `1.11`'s job (ADR-0030).
- [x] **G7** A non-200 with nothing resolving is **not** an empty extraction.
- [x] **G8** Transform chains against a table of fixtures, including
      European decimal commas and multi-currency pages.
- [x] **G9** `structured` wins over `selector` where both would succeed.
- [x] **G10** The chain cannot reach a model at crawl time (ADR-0005).

## Mutation matrix

Thirty-four mutations across five modules. Baseline: 64 passed.
**All red but one, which is an equivalent mutant** (see below).

Highlights, rather than every row:

| Mutation                                                | Red                  |
| ------------------------------------------------------- | -------------------- |
| `parse_decimal` guesses on `1,234`                      | G8                   |
| `POA` becomes `Decimal(0)`                              | G4, G8               |
| a currency is guessed when none is determinable         | G8                   |
| the domain default beats the symbol                     | G8                   |
| `strip_currency` drops the sign                         | G8                   |
| `empty_extraction` ignores the status                   | G7                   |
| `empty_extraction` uses `any` instead of `all`          | G5, G6               |
| a genuine `0` counts as empty                           | G7                   |
| the chain stops on a hollow rung                        | G2, G9               |
| **the chain order is reversed**                         | **G9 — after a fix** |
| "no template" returns `{}`                              | ADR-0027 §3          |
| **the currency rule accepts a missing code**            | **new test**         |
| **the currency rule accepts a non-decimal**             | **new test**         |
| **`saw` loses the raw text**                            | **G4 — after a fix** |
| **the fallback selector is ignored**                    | **new test**         |
| `url` / `integer` / `min_count` / `matches` always pass | new tests            |

### Six blind spots, and two of them were vacuous tests

The first matrix left **six** mutations green — the most of any slice so
far — and two of those were tests that looked right and proved nothing:

- **The ordering test was vacuous.** It used the orbis JSON-LD fixture with
  the vantage template, whose selectors match nothing on that page: rung 2
  produced an empty extraction, so the chain ended at rung 1 **whichever
  order it tried them in**. Reversing the chain left the whole suite green.
  It now uses a page carrying both, with _different values_, and asserts
  which value came back.
- **`"POA" in saw` passed against a `saw` of the whole repr.** `str({'amount':
None, 'currency': 'GBP', 'raw': 'POA'})` contains the substring, so
  dropping the `raw` lookup was invisible. The assertion is now exact.

The other four were simply uncovered: the `currency` rule's missing-code and
non-decimal branches, `FieldRule.fallback`, and every rule other than
`non_empty` and `currency`. A rule tested only on values it accepts is
indistinguishable from a rule that accepts everything — which is what
`matches` and `url` turned out to be.

### The one that stays green, and why it is not a gap

`structured` returning `{}` instead of `None` when no product is found. The
chain treats the two identically — `fields is None` continues, and
`empty_extraction` on an all-empty mapping continues — so there is **no
observable difference** to assert. An equivalent mutant, recorded as such
rather than papered over with a test of an internal.

## Handoff log

- **planner/backend/test** — as above. `make check` green, 64 tests in this
  slice.

## Open questions

1. **`extruct` brings `requests` into the image.** ADR-0028 and ADR-0017
   both argued against two HTTP clients in one service, and this is one —
   transitively, unimported, but present and importable. Spec 003 §1 says
   "do not hand-roll JSON-LD parsing", so the dependency is specified; the
   transitive cost was not. **For the human:** worth a line in ADR-0028, or a
   check that nothing imports `requests`.
2. **`Template.url_pattern` is `str` but its docstring says compiled.** The
   docstring argues the compile should happen "at the repository boundary"
   so an unusable regex fails when the template is read rather than
   mid-crawl. Nothing compiles it today and nothing matches on it yet —
   `1.11`/`1.13` will. **For the human:** either the annotation or the
   docstring is wrong, and the docstring has the better argument.
3. **The `date` rule's `datetime`/`date` branch was dead code** and is
   removed: `FieldValue` cannot hold one and no transform in spec 003 §2
   produces one. If a future transform does, the branch comes back with a
   test.
