# 0006 — Templates are versioned and keyed on (domain, url_pattern)

**Status:** Accepted · 2026-10-15

## Context

A template is a set of selectors. Two questions decide its shape: what is it
scoped to, and what happens when it changes.

Scoping to the domain is the obvious choice and it works until the first site
that needs different selectors for its listing pages and its product pages —
which is most sites — or different rules per category section, which is
common in supplier catalogues.

Editing in place is also the obvious choice, and it destroys the ability to
attribute a data change to its cause.

## Decision

- Templates are keyed on **`(domain_id, url_pattern)`**, with `url_pattern` a
  regex matched against path and query.
- Approving a template creates a **new row with an incremented version** and
  flips `is_active`. A partial unique index guarantees exactly one active
  template per pattern while every prior version stays readable.
- Every `page_observations` row records the `template_id` that produced it.
- `parent_template_id` exists as a nullable self-reference and is **never
  populated** (see Consequences).

## Consequences

- A price that moved because the site changed is distinguishable from one that
  moved because the operator fixed a selector. Charts mark template-version
  changes for exactly this reason.
- Reverting a bad template edit is flipping `is_active` back, not
  reconstructing selectors from memory.
- Keying on `(domain, url_pattern)` from day one avoids a migration that would
  touch every row.
- **On inheritance:** the operator expects these domains to be bespoke, so
  template inheritance is hedged rather than built. The column costs one
  migration line. A resolution layer that nobody uses would cost every future
  change to template handling. If a platform family (Shopify, WooCommerce)
  turns up, a child overriding a parent's field map is an additive change.
- **Cost:** more rows, and the UI must always show which version is active,
  which is one more thing to get right on three screens.
