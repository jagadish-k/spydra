# 007 — LLM proposal and verification

**Phase 4** · depends on 003, 005 · ADR-0005, ADR-0009, ADR-0020

The model proposes CSS selectors once per template. It never extracts at
crawl time and it is never trusted.

---

## 1. Setup

`llama-server` runs natively on the host (ADR-0009), reached at
`LLM_BASE_URL` (default `http://host.docker.internal:8080`).

Because inference is once-per-template rather than once-per-page, **quality
of proposals matters far more than tokens per second**. That inverts the usual
local-LLM advice and is the reason for the model choice and for best-of-N
(ADR-0020).

| Tier | Model | Footprint | Used for |
| --- | --- | --- | --- |
| primary | Qwen3-Coder 30B-A3B (MoE) | ~20 GB Q4 | every proposal; ~3 B active params makes N=5 sampling affordable |
| escalation | Qwen 3.6 27B dense | ~22 GB Q4 | retried fields where no sample scored above 60 |

Both fit the Mac Studio Ultra's unified memory with room for the OS. Load one
at a time; `llama-server` is restarted to switch tiers, which is acceptable
because escalation is rare and authoring is interactive, not batched.

The application talks to it behind the `LLMClient` port. Swapping models, or
comparing against a hosted API, touches one adapter. **Model identity and
sample index are recorded in `provenance`** (spec 013 §2) so a bad batch of
selectors can be traced to the model that produced it.

## 2. Preprocessing — the step that matters

**Do not send raw HTML.** A product page is often 500 KB of markup, most of it
irrelevant and expensive to attend to.

1. Strip `<script>`, `<style>`, comments, SVG bodies, `<svg>` contents,
   base64 data URIs.
2. Collapse to a skeleton: tag name, `id`, `class`, and text content
   truncated to 80 characters per node.
3. Keep nodes with visible text or `src`/`href`; drop empty wrappers.
4. Prefer the main content region (`<main>`, `[role=main]`, the largest text
   block) when the node budget is tight.
5. Cap at ~3,000 nodes.

Emit a stable, line-oriented format with an index per node so the model can
refer to nodes precisely:

```
[12] div.product-info
[13]   h1.product-title "Zirconia Flap Disc 115 mm · 120 grit"
[14]   span[itemprop=price] "£4.85"
[15]   div.brand-name > a "Vantage Abrasives Ltd"
```

The same skeleton is shown in the review screen's "DOM skeleton" toggle, so
the operator sees exactly what the model saw.

## 3. The request

Use the server's JSON-schema-constrained output (`response_format`) rather
than asking politely for JSON and parsing hopefully.

```json
{ "fields": {
    "title":  {"selector": "h1.product-title", "attr": "text",
               "confidence": 0.95, "resolves_to": "Zirconia Flap Disc 115 mm · 120 grit"},
    "price":  {"selector": "span[itemprop='price']", "attr": "text",
               "confidence": 0.91, "resolves_to": "£4.85"} },
  "discovery": {"product_links": "a.product-card__link",
                "next_page": "a[rel='next']"},
  "notes": "Price appears once; a second .price node is a strike-through RRP." }
```

**N=5 samples at temperature 0.7**, not one at 0.1 (ADR-0020). The reasoning
is counter-intuitive and worth stating: a greedy decode gives one answer with
no way to tell whether it is good, whereas five varied answers can be ranked
by *deterministic verification against the real DOM* — so sampling diversity
is free accuracy when a cheap oracle exists. It does here.

Samples are scored by ADR-0020 §scoring and **merged per field, not per
sample** (spec 013 §4): the best `title` may come from sample 1 and the best
`images` from sample 4.

One retry on malformed output per sample, then drop that sample. Five
malformed samples fail the proposal with a clear error — do not loop.

## 4. Verification — non-negotiable

Every proposal is checked against the **real DOM** before a human sees it:

```
for each proposed field:
    nodes = real_dom.select(selector)
    if nodes is empty                      → discard, reason 'no_match'
    if normalise(nodes[0].text) != normalise(claim)
                                           → discard, reason 'claim_mismatch'
    if many=false and len(nodes) > 1       → keep, flag 'ambiguous'
    else                                   → keep, verified
```

Discarded selectors never reach the review screen. This converts a
probabilistic suggestion into a checked candidate and makes a weak proposal
fail loudly rather than produce plausible wrong data.

Verification results are recorded on `unknown_pages.llm_proposal` so the
review screen can show what was proposed, what survived, and why the rest did
not.

## 5. Confidence

The model's own score is **advisory only**. The displayed confidence is
derived:

| Displayed | When |
| --- | --- |
| `high` | verified, unique match, resolves on all samples |
| `good` | verified, unique match, resolves on most samples |
| `medium` | verified but ambiguous, or a positional selector |
| `low` | verified on this page, fails on ≥1 sample, or `nth-of-type` |

A selector using `nth-child`/`nth-of-type` is **never** rated above `medium` —
positional selectors are the ones that silently break on redesign.

## 6. Failure behaviour

| Condition | Behaviour |
| --- | --- |
| `llama-server` unreachable | 503 problem detail from `/propose`. **Crawling is unaffected.** Sidebar shows the dot red. |
| Malformed output on every sample | Fail the proposal, record the raw responses, surface "model output unusable". |
| No field scores above 60 | Escalate those fields to the dense model once; if still below, route to manual authoring. |
| All fields discarded | Template stays a draft, reason `llm_low_confidence`, routed to the review inbox for manual authoring. |
| Timeout (>180 s for the full N=5 batch) | Abort and keep whatever samples returned. |

## 7. Acceptance

- [ ] A proposal whose claimed text does not match the DOM is discarded before
      reaching the API response.
- [ ] A selector matching zero nodes never appears on the review screen.
- [ ] `nth-of-type` selectors are capped at `medium` confidence.
- [ ] `llama-server` down returns a clear 503 from `/propose` and does not
      affect `POST /api/runs`.
- [ ] Skeletonisation of a 500 KB fixture produces under 3,000 nodes and
      retains the price, title and image nodes.
- [ ] The adapter is behind `LLMClient`; a fake client drives all tests
      without a model running.
- [ ] Five samples are requested and ranked; a case exists where the winning
      `price` and the winning `title` come from different samples.
- [ ] One malformed sample does not fail the proposal.
- [ ] `provenance.model` records the tier and sample index that won each
      field.
- [ ] Escalation to the dense model fires only for fields scoring below 60.
