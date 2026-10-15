# 014 — Visual playground

**Phase 6** · depends on 012, 013 · ADR-0019, ADR-0020

Click a page, get a selector. The playground is the third front door to the
one authoring pipeline (ADR-0019); everything it produces is a
`FieldCandidate` (spec 013 §2) and goes through the same verify/merge/rank
path.

---

## 1. No iframe

The obvious implementation — drop the fetched page in an `<iframe>` and
attach click handlers — is the one to reject. Supplier pages carry
third-party script, and an iframe would run it inside the app origin with the
operator's session available. `sandbox` blocks script but then the page
renders wrong, and cross-origin framing means no DOM access anyway, which was
the entire point.

**So no untrusted HTML or script ever enters the browser.** The render sidecar
flattens the page into a screenshot plus a geometry list, and the playground
is a canvas with an overlay. Clicks hit the overlay, not the page.

The cost is real: no hover states, no interacting with tabs or accordions,
nothing behind a click. §6 covers that.

## 2. `/inspect` — sidecar extension

Added to spec 012. Same browser, same context lifecycle, same isolation.

```
POST /inspect
{
  "url": "https://example.com/products/flap-disc",
  "viewport": {"width": 1440, "height": 900},
  "full_page": true,
  "wait_until": "networkidle",
  "max_elements": 4000,
  "reveal": [                                 // §2a
    {"selector": "details:not([open])", "action": "click", "all": true},
    {"selector": "nav.mega > li", "action": "hover", "all": true, "wait_ms": 150}
  ]
}
→ 200
{
  "screenshot": "data:image/webp;base64,…",   // full-page, 1x
  "page": {"width": 1440, "height": 5120, "final_url": "…"},
  "elements": [
    {"i": 14,                                  // index, shared with the skeleton
     "tag": "span",
     "box": [412, 338, 96, 28],                // x, y, w, h in page coords
     "text": "£4.85",
     "id": null,
     "classes": ["price", "price--now"],
     "attrs": {"itemprop": "price"},           // semantic attrs only (§3)
     "path": "html>body>div:nth(3)>main>div:nth(1)>span:nth(2)",
     "parent": 11,
     "depth": 7,
     "interactive": false,
     "occluded": false}
  ],
  "skeleton": "[12] div.product-info\n[13]   h1.product-title \"…\"\n…",
  "revealed": {"attempted": 14, "succeeded": 12, "capped": false},
  "network": [                                 // §2a
    {"method": "GET", "url": "https://example.com/api/nav/children?id=42",
     "status": 200, "content_type": "application/json", "bytes": 4210,
     "during": "reveal"}
  ]
}
```

The `i` index is the **same index spec 007 §2 emits**. One page, one node
numbering, shared by the skeleton the model reads, the overlay the operator
clicks, and the transcript. Without that, correlating a click to a chat
instruction means fuzzy matching on text.

Element harvesting runs in the page as one `evaluate` call:

- Walk `document.body`, keep elements whose `getBoundingClientRect()` has
  non-zero area and whose computed `visibility`/`display` is not hidden.
- Keep an element if it has direct text, an `src`/`href`, or more than one
  element child (containers matter for §5).
- Drop `script`, `style`, `noscript`, `template`, `svg` descendants.
- `text` is `innerText` truncated to 200 chars.
- Cap at `max_elements`, breadth-first from `body`, so the cut falls on deep
  leaves rather than structure.

**Scroll the full page before capturing.** Lazy-loaded images and
intersection-observer content are otherwise absent from both screenshot and
geometry, and the operator clicks a blank box.

| Code | Meaning |
| --- | --- |
| 200 | Captured |
| 413 | Page exceeded `max_elements` after the cap; returns what fits, `truncated: true` |
| 502 / 504 / 503 | As `/render` (spec 012 §1) |

Response size is the risk: a full-page WebP at 1x plus 4,000 elements runs
1–3 MB. Cap at 8 MB, serve the screenshot as a separate
`GET /inspect/{token}/screenshot` when it exceeds 2 MB, and never log the
body.

## 2a. `reveal` — content behind interaction

Tab panels, accordions, "show more specs" and cascading menus. A bounded
pre-capture step, not a scripted interaction recorder.

```jsonc
{"selector": "nav.mega > li",   // what to act on
 "action": "hover",             // hover | click
 "all": true,                   // every match, or just the first
 "wait_ms": 150}                // settle time after each
```

| Bound | Value | Why |
| --- | --- | --- |
| Elements per capture | 20 | past this it is a crawl, not a capture |
| Total reveal time | 3 s | a slow menu is a worse discovery rule than no menu |
| Steps per request | 5 | five ordered steps describe any real menu |
| Nesting | none | a reveal cannot depend on a previous reveal's output |

The last bound is the one that keeps this from growing into a scripting
language. Two-level cascades are reachable by two *independent* selectors
(`nav.mega > li` then `nav.mega .submenu > li`), because the first step's
hover is still in effect when the second runs. A reveal that genuinely needs
output from an earlier step is a case for a hand-written selector, not for a
bigger reveal grammar.

`revealed` reports what happened; `capped: true` means the bound was hit and
the capture is incomplete, which the UI must say rather than silently showing
a partial page.

**The network log is the useful half.** `network[]` lists requests issued
during the capture, flagged `during: "reveal"` when a reveal step caused
them. A menu that fetches its children over XHR therefore hands the operator
the endpoint instead of a selector — a far more durable discovery rule than
any hover (spec 004 §3a, case C).

**Reveal steps are stored on the template** when the operator approves one,
so a run reproduces exactly the capture that was reviewed. A reveal invented
at crawl time would mean the run discovering from a page the operator never
saw.

## 3. Attribute filtering

`attrs` carries only attributes that make a selector durable:

**Kept:** `id`, `itemprop`, `itemtype`, `role`, `name`, `type`, `data-*`,
`aria-label`, `aria-labelledby`, `href`, `src`, `alt`, `title`.

**Dropped:** `style`, `class` (goes to `classes`), event handlers, and
anything above 120 characters.

Classes are kept but **ranked**, because most are worthless for selectors:

```
reject  hashed            /^[a-z]{1,3}-?[a-f0-9]{5,}$/   css-1x4bf9k, sc-fzqNJr
reject  utility           tailwind-shaped: ^(mt|px|py|flex|grid|text|bg|w|h)-
reject  state             is-active, open, selected, hover
prefer  semantic          product-title, price, sku, breadcrumb
```

A selector built on a rejected class is penalised 20 points by the ADR-0020
scorer. The playground filters them before generalisation so the penalty is
rarely reached — the scorer is the backstop, not the filter.

## 4. Interaction model

One screen, three modes on a segmented control (spec 006 / SCREENS):

| Mode | What it does |
| --- | --- |
| **Preview** | screenshot only, no overlay — read the page |
| **Select** | overlay live; hover highlights, click assigns |
| **Skeleton** | the `skeleton` text, node indices visible, click-to-assign too |

In Select mode:

1. Operator picks a target field from the vocabulary list (spec 013 §3).
2. Hover draws the box of the smallest element containing the cursor; the
   breadcrumb shows its ancestor chain, and `[` / `]` walks up and down it.
   Picking the right node is the single most error-prone step and a
   keyboard-driven ancestor walk makes it cheap.
3. Click records an **example**: `{sample_url, i, node_path, text, box}`.
4. Generalisation (§5) runs immediately and the proposed selector appears
   with its match count drawn on the page — every match highlighted, not
   just the clicked one. Six highlights when the operator expected one is
   instant, legible feedback.
5. `POST /api/crawler/drafts/{id}/select` persists the example and returns
   the verified `FieldCandidate`.

**Multi-example is the main affordance, not an advanced feature.** Clicking
the same field on sample page 2 is what turns a brittle positional selector
into a durable one (§5 layer 2). The UI asks for it after the first click
rather than waiting for the operator to discover it.

Shift-click on a sibling of an existing example marks a `many: true` field
(images, spec rows).

## 5. Generalisation

Three layers, cheapest first. Each proposes candidates; all go to the
ADR-0020 verifier and scorer, which decides.

### Layer 1 — heuristic, single example

Walk the clicked node's ancestor chain outward and emit, in preference order:

```
1  #id                                    if id is non-hashed and unique
2  [itemprop=…] / [data-field=…]          semantic attribute on the node
3  tag[semantic-attr]                      scoped by nearest semantic ancestor
4  .semantic-class                         if it resolves uniquely
5  ancestor-semantic > … > tag             shortest chain of kept classes
6  :nth-of-type path                       last resort, flagged brittle
```

Stop at the first candidate that resolves uniquely and matches the clicked
text, but **emit the next two as well** — layer 1's first pick is wrong often
enough that the verifier needs alternatives on sample pages 2–5.

### Layer 2 — multi-example

Two or more examples of the same field, ideally on different sample URLs.
Compute the common structure:

- Intersect the kept-class sets, semantic attributes and tag names at each
  depth of the two ancestor chains, aligned from the clicked node upward.
- Drop every positional index that differs between examples. This is the
  whole trick: `div:nth(3)` on one page and `div:nth(5)` on another proves
  the index is not part of the pattern.
- Keep an index only where it is identical across all examples *and* no
  non-positional discriminator exists.

Two examples from two URLs beat ten clicks on one page. The UI says so.

### Layer 3 — LLM refinement

Only when layers 1 and 2 produce nothing scoring above 60. The model gets the
skeleton, the example node indices, and the failing candidates, and is asked
for selectors — never for values (ADR-0005). Best-of-N, N=5 (ADR-0020).

`provenance.generalised_by` records which layer won. Expect layer 2 to carry
most fields; if layer 3 is winning routinely, layers 1–2 have a bug worth
finding.

## 6. Repeating containers

Listing pages are the reason this screen exists, and they need a container,
not a field.

Detection, after the operator clicks one card:

1. Walk up from the clicked node until an ancestor has **three or more
   siblings with the same tag and an overlapping kept-class set**.
2. Confirm by structural similarity: each sibling's child tag sequence must
   match the clicked one at ≥70%. A `<li>` of filter checkboxes is excluded
   this way.
3. Confirm by geometry: sibling boxes share a width or an x-origin within
   8 px. Grid and list layouts both satisfy this; unrelated siblings do not.
4. Propose that ancestor as `container`, with the count drawn on screen.

Field selectors inside a container are then **relative to it**, and
`many: true` is implied. Pagination and the product link are the two
discovery selectors the listing playground must produce; both are ordinary
fields whose target is `discovery` (spec 004).

## 7. Content behind interaction

Unreachable in the overlay model: tab panels, accordions, "show more specs",
anything requiring a click. Three escapes, in order:

1. **Reveal (§2a).** A bounded hover/click pass before capture. Covers
   accordions, `<details>`, tab panels and most cascading menus with no
   bespoke work.
2. **Skeleton mode.** Hidden-but-present DOM appears in the skeleton even
   when it is not in the screenshot, and is clickable there. Most "hidden"
   spec tables are in the markup already.
3. **Hand-written selector.** The form mode of the same draft, verified
   identically.

Not planned: a scripted interaction recorder — ordered, nested, conditional
steps with state between them. It is a large build with a large failure
surface for a case that escapes 1–3 rarely, and when it does, the honest
answer is usually that the site wants an API call rather than a crawl
(spec 004 §3a, case C).

## 8. Caching

`/inspect` results are cached per `(url, viewport, full_page)` for 30 minutes
in `/data/inspect-cache`, keyed by hash.

This is a politeness feature before it is a performance one. An authoring
session re-renders the same five pages continuously, and without the cache
the playground becomes the rudest component in a system whose first principle
is politeness (ADR-0004). **Cache hits do not claim the per-domain gate;
misses do**, like any other fetch.

## 9. Acceptance

- [ ] No untrusted HTML or script is ever inserted into the app document
      (assert: the playground route creates no iframe and calls no
      `innerHTML` with fetched content).
- [ ] A page fetching `http://api:8000/…` during `/inspect` cannot reach it.
- [ ] Node indices in `elements[]` and `skeleton` refer to the same nodes.
- [ ] Clicking a price on one page yields a working selector; clicking it on
      a second page replaces a positional selector with a structural one, and
      `generalised_by` changes to `multi_example`.
- [ ] A selector matching six nodes highlights all six before the operator
      accepts it.
- [ ] Hashed and utility classes never appear in a layer-1 or layer-2
      candidate.
- [ ] `[` / `]` walk the ancestor chain and the breadcrumb follows.
- [ ] Container detection finds a product grid of 24 cards and rejects a
      sidebar filter list of 24 checkboxes.
- [ ] A lazy-loaded image below the fold has a non-zero box.
- [ ] A `reveal` step opens a `<details>` spec table and its rows appear in
      `elements[]`.
- [ ] A hover reveal on a two-level mega-menu exposes both levels via two
      independent selectors.
- [ ] A reveal set of 40 elements stops at 20 and returns `capped: true`,
      and the UI says the capture is partial.
- [ ] An XHR fired during reveal appears in `network[]` with
      `during: "reveal"`.
- [ ] Re-inspecting the same URL within 30 minutes issues no network request
      and claims no politeness lock.
- [ ] A playground-authored draft and a chat-authored draft merge into one
      template (spec 013 §4).
- [ ] A 12,000-element page returns `truncated: true` and stays under the
      response cap.
