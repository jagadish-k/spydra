# 0020 — Best-of-N sampling, ranked by deterministic verification

**Status:** Accepted · 2026-10-15

## Context

Conventional local-LLM advice is to run the largest model your hardware
allows, because a single-shot answer is all you get and quality scales with
parameters. That advice assumes **no verifier**.

This system has one. Every proposed selector is run against the real DOM and
compared to what the model claimed (ADR-0005). Verification is exact, free,
and takes microseconds. A wrong selector is detected with certainty, not
estimated.

That inverts the usual calculus. If you can tell good from bad for free, you
do not need to be right first time — you need to be right *once* across
several attempts.

And inference happens **once per template**, not once per page, so spending
five times the compute costs seconds of wall clock on a machine that is
otherwise idle.

## Decision

**Sample N candidate proposals, verify all, rank the survivors.**

- `N = 5` by default, temperature 0.7, same prompt.
- Each candidate is verified independently. Candidates that fail entirely
  are discarded.
- Surviving candidates are merged **per field** — the best selector for
  `price` may come from candidate 2 and the best for `images` from
  candidate 4. There is no reason to take one candidate whole.
- Ranking is a deterministic scoring function, so the same candidate set
  always produces the same winner:

```
score(selector, field) =
    + 40   resolves on every sample URL
    + 25   resolves to the claimed text
    + 15   uses a semantic hook (id, itemprop, data-*, aria-*)
    + 10   cardinality matches intent (1 for single, N for many)
    +  5   short (fewer than 4 combinators)
    - 30   uses nth-child / nth-of-type          (positional — breaks on redesign)
    - 20   depends on a utility or hashed class  (.px-4, ._price_1a2b3)
    - 15   resolves on this page only
```

A positional selector can still win if nothing else resolves — but it is
capped at `medium` confidence (spec 007 §5) and flagged in review, because
positional selectors are the ones that silently break.

**Model tiering:**

| Tier | Model | When |
| --- | --- | --- |
| Primary | **Qwen3-Coder 30B-A3B** (MoE, ~20 GB Q4) | every proposal |
| Escalation | **Qwen 3.6 27B dense** (~22 GB Q4) | when no candidate yields a verified selector for a required field |

MoE suits Apple unified memory: the whole model sits in RAM while only ~3 B
parameters activate, so five samples over a 40 K-token skeleton stay
tolerable. Coder-tuned matters because a CSS selector is closer to code than
to prose.

## Consequences

- Accuracy comes from sampling and verification rather than from parameters,
  which means a 30 B model with N=5 can beat a much larger model at N=1 on
  this task — at a fraction of the prefill cost.
- Per-field merging means one bad field does not sink an otherwise good
  proposal.
- The scoring function is explicit and tunable, and it encodes real knowledge
  about which selectors survive redesigns. That knowledge lives in code
  rather than in a prompt.
- **The playground reduces model dependence further.** When the operator
  points at the element, the model's job collapses from "find the price among
  3,000 nodes" to "generalise this selector" — which the primary tier does
  reliably and which the heuristics often handle with no model at all.
- **Cost:** five times the inference and a ranking function to maintain.
  Wall clock is seconds per template, so the compute is immaterial; the
  scoring weights are a real maintenance surface and will need tuning against
  observed breakages. Treat the weights as a tunable, keep them in one place,
  and change them with evidence from the extraction-health report rather than
  by intuition.
- Benchmark the tiers on **your own fixtures** — twenty real supplier pages,
  measuring verified-selector accuracy — not on public coding benchmarks,
  which measure something else.
