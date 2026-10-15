# 0005 — The LLM proposes selectors and never extracts

**Status:** Accepted · 2026-10-15

## Context

The obvious use of a local model in a crawler is to hand it a page and ask for
the fields. That is the design most people reach for, and it is wrong here for
three reasons: it puts a 1–5 s inference on every page, it makes extraction
non-deterministic, and it produces plausible wrong values that are
indistinguishable from right ones.

## Decision

The model is invoked **once per template**, during onboarding or review, to
propose CSS selectors. It is never called during a crawl.

The pipeline is:

1. Fetch one sample page per URL pattern.
2. Skeletonise the DOM — strip scripts, styles, comments, SVG bodies; collapse
   to tag + id + class + truncated text; cap at a few thousand nodes. A raw
   product page is often 500 KB of markup, most of it irrelevant and expensive
   to attend to.
3. Ask for strict JSON: a selector per requested field, a confidence score,
   and the text the model believes the selector resolves to.
4. **Verify deterministically.** The application runs each proposed selector
   against the real DOM and compares the result to the model's claim. A
   selector that does not resolve, or resolves to something different, is
   discarded before a human ever sees it.
5. The operator reviews what survives, edits it, and approves.

## Consequences

- Extraction at crawl time is pure, deterministic CSS selection. The same page
  always yields the same values.
- The model can be large and slow, because it runs once per template rather
  than once per page. Quality of proposals matters far more than tokens per
  second.
- **`llama-server` being down blocks onboarding but not crawling.** The model
  is not in the crawl path.
- Verification converts a probabilistic suggestion into a checked candidate,
  so a weak proposal fails loudly instead of producing plausible wrong data.
- **Cost:** novel page layouts need a human in the loop. At one template per
  domain and roughly six domains a month, 1,200 domains is years of review.
  Review throughput — not technology — is this system's real constraint, and
  batch review (phase 3) exists to attack it.

## Alternatives considered

**Model extracts fields at crawl time.** Rejected: slow, non-deterministic,
and it fails silently in exactly the way that corrupts a dataset.

**Model classifies the page and selects a pre-written template.** Folded in —
pattern matching on URL does this job without inference.
