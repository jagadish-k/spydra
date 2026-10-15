# 007 — LLM proposal and verification

**Phase 4** · depends on 003, 005 · ADR-0005, ADR-0009

The model proposes CSS selectors once per template. It never extracts at
crawl time and it is never trusted.

---

## 1. Setup

`llama-server` runs natively on the host (ADR-0009), reached at
`LLM_BASE_URL` (default `http://host.docker.internal:8080`).

A 30B-class instruction-tuned model. The Mac Studio Ultra's unified memory
accommodates it comfortably, and because inference is once-per-template,
**quality of proposals matters far more than tokens per second**.

The application talks to it behind the `LLMClient` port. Swapping models, or
comparing against a hosted API, touches one adapter.

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

Temperature 0.1. Deterministic seed. One retry on malformed output, then fail
with a clear error — do not loop.

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
| Malformed output twice | Fail the proposal, record the raw response, surface "model output unusable". |
| All fields discarded | Template stays a draft, reason `llm_low_confidence`, routed to the review inbox for manual authoring. |
| Timeout (>120 s) | Abort; a 30B model on this hardware should take seconds. |

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
