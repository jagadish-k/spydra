# 013 — Template authoring service

**Phases 3 and 4** · ADR-0019, ADR-0020

| Sections  | Phase | Depends on | Built by                 |
| --------- | ----- | ---------- | ------------------------ |
| §1–§4     | **3** | 003, 005   | BUILD_PLAN `3.1`–`3.3`   |
| §5        | **3** | §1–§4      | BUILD_PLAN `3.4`         |
| §6 (chat) | **4** | §1–§4, 007 | BUILD_PLAN `4.11`–`4.12` |

**The split is the point** (ADR-0019). The draft model, the vocabulary and the
verify/merge/rank path are built in phase 3 with hand-written selectors as
their only input, so phase 4 adds a _mode_ rather than a pipeline. Only §6
needs the model, and only §6 depends on spec 007 — a reader doing `3.1` was
previously told by this header that they were in phase 4 and needed an LLM.

One pipeline, three front doors. This spec defines the shared draft model,
the canonical field vocabulary, and the merge/verify/rank path every mode
goes through.

---

## 1. The draft

```sql
CREATE TABLE crawl.template_drafts (
  id           BIGSERIAL PRIMARY KEY,
  domain_id    BIGINT NOT NULL REFERENCES crawl.domains(id) ON DELETE CASCADE,
  url_pattern  TEXT NOT NULL,
  page_kind    TEXT NOT NULL,              -- 'listing' | 'product'
  parent_id    BIGINT REFERENCES crawl.templates(id),  -- editing an existing version
  state        TEXT NOT NULL DEFAULT 'open',  -- open|verifying|ready|discarded
  fields       JSONB NOT NULL DEFAULT '{}',   -- field name → FieldCandidate (§2)
  discovery    JSONB NOT NULL DEFAULT '{}',
  sample_urls  TEXT[] NOT NULL DEFAULT '{}',
  container    JSONB,                      -- repeating-container selector, if any
  transcript   JSONB NOT NULL DEFAULT '[]',   -- chat mode: the conversation
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON crawl.template_drafts (domain_id, state);
```

A draft is working state. Approving it writes a new row in
`crawl.templates` with an incremented version (ADR-0006) and marks the draft
`discarded`. **Drafts are never crawled from.**

## 2. FieldCandidate

The unit all three modes produce.

```jsonc
{
  "selector": "span[itemprop='price']",
  "attr": "text",
  "many": false,
  "required": false,
  // always false — ADR-0027 makes `required` inert and the loader
  // rejects `true`. The authoring pipeline never sets it.
  "transform": ["strip_currency", "parse_decimal"],
  "validation": ["currency"],
  "fallback": null,

  "provenance": {
    "mode": "playground", // form | chat | playground
    "examples": [
      // playground: what was clicked
      {
        "sample_url": "…/flap-disc",
        "node_path": "html>body>div:nth(3)>…",
        "text": "£4.85",
        "box": [412, 338, 96, 28],
      },
    ],
    "prompt": null, // chat: the instruction that produced it
    "model": null, // chat: model + sample index (ADR-0020)
    "generalised_by": "multi_example", // heuristic | multi_example | llm | manual
  },

  "verification": {
    "verified": true,
    "match_count": 1,
    "resolved": "£4.85",
    "per_sample": { "…/flap-disc": "pass", "…/SKU-8841": "fail" },
    "score": 85, // ADR-0020 ranking
    "confidence": "high",
  },
}
```

**Provenance is load-bearing, not bookkeeping.** When a selector breaks after
a redesign, stored click examples let the system re-generalise against the new
DOM without the operator starting over. Do not drop it to save space.

## 3. Canonical field vocabulary

```sql
CREATE TABLE crawl.field_vocabulary (
  name        TEXT PRIMARY KEY,       -- 'price_amount'
  label       TEXT NOT NULL,          -- 'Price'
  target      TEXT NOT NULL,          -- 'column' | 'attributes' | 'supplier'
  column_name TEXT,                   -- when target='column'
  data_type   TEXT NOT NULL,          -- text|decimal|integer|url|date|text[]|jsonb
  validation  TEXT[] NOT NULL DEFAULT '{}',
  transform   TEXT[] NOT NULL DEFAULT '{}',
  aliases     TEXT[] NOT NULL DEFAULT '{}',  -- 'cost','unit price','RRP'
  is_core     BOOLEAN NOT NULL DEFAULT FALSE
);
```

Seeded with the typed columns: `title`, `price_amount`, `price_currency`,
`availability`, `vendor`, `category_path`, `description`, `images`, plus
common non-core ones (`sku`, `supplier_ref`, `lead_time`, `moq`, `specs`).

**Every mode resolves user intent against this table before creating a
field.** Chat is prompted with it. The playground offers it as the field
list. The form autocompletes from it.

Why this matters: without it, forty domains end up with `price`, `cost`,
`unit_price` and `price_ex_vat` meaning the same thing, and the
price-change report becomes impossible to write. A genuinely new field is
added to the vocabulary deliberately, not invented per domain.

A field whose `target` is `attributes` lands in JSONB and is **not**
available to cross-domain reports. The UI says so when a new field is
created, because that is the moment the operator can still choose a core
field instead.

## 4. Verify, merge, rank

Shared by all modes.

```
candidates[]  →  verify each against every sample URL
              →  discard: no match | claim mismatch
              →  score  (ADR-0020 §scoring)
              →  merge per field, best score wins
              →  TemplateDraft.fields
```

**Merging is per field, not per candidate.** The best `price` may come from
one LLM sample and the best `images` from another; there is no reason to take
a candidate whole. The same applies across modes — a clicked `price` and a
chat-proposed `description` coexist in one draft.

Verification runs against **all** sample URLs, not just the page in front of
the operator. A selector that resolves here and fails on sample 3 is the
single most common error and it is invisible without this.

## 5. API

```
POST   /api/crawler/drafts                    {domain_id, url_pattern, page_kind, sample_urls}
GET    /api/crawler/drafts/{id}
PATCH  /api/crawler/drafts/{id}               edit a field by hand (form mode)
DELETE /api/crawler/drafts/{id}

POST   /api/crawler/drafts/{id}/chat          {message}  → SSE stream (§6)
POST   /api/crawler/drafts/{id}/select        {field, examples[]}   playground (spec 014)
POST   /api/crawler/drafts/{id}/propose       full LLM proposal, best-of-N
POST   /api/crawler/drafts/{id}/verify        re-run verification
POST   /api/crawler/drafts/{id}/samples       {urls[]}  add sample URLs
POST   /api/crawler/drafts/{id}/approve       → new Template version

GET    /api/crawler/field-vocabulary
POST   /api/crawler/field-vocabulary          add a canonical field
```

## 6. Chat mode

Streams over SSE, same transport as run progress (ADR-0012).

**The chat produces a template, never data.** If "get me the price from these
URLs" returned extracted values, that would be per-page LLM extraction
through the back door — exactly what ADR-0005 rejects, and it would cost
determinism, reproducibility and the audit trail.

The loop:

1. Operator gives sample URLs and an instruction in plain language.
2. The service fetches **1–5 sample pages** (politeness gate applies) and
   skeletonises them (spec 007 §2).
3. The model resolves the instruction against the field vocabulary and
   proposes fields + selectors, best-of-N (ADR-0020).
4. Verification runs. Survivors become `FieldCandidate`s on the draft.
5. The operator sees the draft filling in live and replies to refine:
   _"the price should exclude VAT"_, _"also grab the datasheet link"_.

**Hard limits:**

| Limit                        | Value | Why                                       |
| ---------------------------- | ----- | ----------------------------------------- |
| Sample pages per draft       | 5     | It is authoring, not crawling             |
| Cannot start a run           | —     | Otherwise the politeness model has a hole |
| Cannot modify another domain | —     | A draft is scoped to one domain           |
| Cannot write `templates`     | —     | Only `approve` promotes a draft           |

The chat is a **template-authoring interface that happens to use
conversation**. It is not an agent. If a request needs more than five pages
or touches another domain, it is refused with an explanation, not negotiated.

## 7. Acceptance

- [ ] A draft authored by form, chat and playground in combination produces
      one template, and the approved result is identical in shape to a
      hand-written one.
- [ ] A chat instruction naming "cost" resolves to `price_amount` via the
      vocabulary aliases, not a new field.
- [ ] Creating a non-core field warns that it will not appear in
      cross-domain reports.
- [ ] Per-field merging picks the best selector across LLM samples
      (construct a case where candidate 1 wins `title` and candidate 3 wins
      `price`).
- [ ] A verified selector that fails on sample 3 is flagged before approval.
- [ ] The chat refuses to fetch a sixth sample page and says why.
- [ ] The chat cannot start a run (assert the endpoint is not reachable from
      the chat tool surface).
- [ ] Approving a draft creates a new template version and discards the draft.
- [ ] Provenance survives approval and is readable on the template.
