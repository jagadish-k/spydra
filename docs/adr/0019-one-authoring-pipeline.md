# 0019 — One authoring pipeline, three input modes

**Status:** Accepted · 2026-10-15

## Context

There are three plausible ways to author a template:

1. **Form** — type selectors directly. What the original design assumed.
2. **Chat** — describe what you want in natural language; the model proposes
   fields and selectors from sample pages.
3. **Playground** — render the page and click the things you want.

The temptation is to build three features. That would be a mistake. Each
would grow its own verification, its own notion of a draft, its own
approval, and within a month a chat-authored template would behave
differently from a clicked one for reasons nobody could explain.

The deeper point: **all three produce the same artifact.** A candidate field
map — field name, selector, transforms, validation. They differ only in how
a human expresses intent.

## Decision

**One pipeline. Three front doors.**

```
form ─────┐
chat ─────┼──→ TemplateDraft ──→ deterministic ──→ review ──→ approve ──→ Template
playground┘      (candidate       verification      screen                (versioned)
                  field map)
```

- Every mode emits a `TemplateDraft`, specified in
  [spec 013](../specs/013-template-authoring.md).
- Every draft goes through the **same** verification (ADR-0005): run each
  selector against the real DOM, discard what does not resolve or does not
  match its claim.
- Every draft lands on the **same review screen**, which is the convergence
  point and the only place a template becomes active.
- Modes can be mixed on one draft. Click three fields, describe the fourth,
  hand-edit the fifth.

**Each field records its provenance** — which mode produced it, and for the
playground, the elements that were clicked. This is not bookkeeping: when a
selector breaks after a redesign, the stored click examples let the system
re-generalise against the new DOM instead of making the operator start over.

**A canonical field vocabulary is shared by all three modes.** Without it,
chat invents `price`, `cost`, `unit_price` and `price_ex_vat` across four
domains and cross-domain reporting quietly dies. The vocabulary maps to the
typed columns where a field fits and to `attributes` JSONB where it does
not.

## Consequences

- One verification path, one review screen, one approval. A template behaves
  identically regardless of how it was authored.
- A new input mode later — import from a competitor's config, infer from a
  sitemap — is a new front door, not a new system.
- Provenance makes repair cheap: a broken selector with stored click
  examples is re-generalisable without human input.
- **Cost:** `TemplateDraft` has to be rich enough for three quite different
  UIs, which makes it a more complicated model than any one mode needs. The
  playground in particular wants element references and screenshots that the
  form mode has no use for. Accepted — the alternative is three divergent
  implementations of the same thing.
- **The draft model is the thing to get right.** If it ends up with
  mode-specific branches threaded through the verification or review code,
  the abstraction has failed and it would be better to admit that than to
  keep patching it.
