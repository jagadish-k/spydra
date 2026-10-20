# Spydra — screens

**This file is the screen registry. It is the single source of truth for
which screens exist, how many there are, and where each one is drawn**
(ADR-0031). No other document enumerates screens; everything else references
this table. If a screen is not in it, it does not exist — and a screen that
is built without a row here is the defect, not the row.

## The registry

**Eleven screens. Ten designed. Eleven top-level layouts. Fifty-six frames.**
Screen 11 (Schedules) has a full backend spec and no design — see the defects
below. The other ten are drawn complete.
The counts differ for one reason and it is not a discrepancy: screen 4 has
three modes (§4), and its Select mode is a different enough layout that
Figma and the mockups each give it its own top-level artifact. Counting
drawn artifacts gives eleven; counting designed screens gives ten. Both are
correct about different things, and every audit that reported a "missing
eleventh screen" had found this and not the real gap, which is Schedules.

Figma file [`GeJPFXY4CicHBdzLMyXG2E`](https://www.figma.com/design/GeJPFXY4CicHBdzLMyXG2E/Spydra),
page `🖥 Screens` (`3:139`).

| #   | Screen          | Figma base | Mockup                                                           | Spec     | Built by | Frames |
| --- | --------------- | ---------- | ---------------------------------------------------------------- | -------- | -------- | -----: |
| 1   | Domains         | `7:2`      | [`domains.html`](../design/mockups/domains.html)                 | 006      | `3.10`   |      7 |
| 2   | Domain detail   | `19:1082`  | [`domain-detail.html`](../design/mockups/domain-detail.html)     | 006, 013 | `3.12`   |      4 |
| 3   | Seeds           | `18:1312`  | [`seeds.html`](../design/mockups/seeds.html)                     | 004      | `3.13`   |      4 |
| 4   | Template review | `13:190`   | [`template-review.html`](../design/mockups/template-review.html) | 013      | `3.14`   |      5 |
| 4·S | ↳ Select mode   | `27:1548`  | [`playground.html`](../design/mockups/playground.html)           | 014      | `6.10`   |      4 |
| 4·K | ↳ Skeleton mode | **none**   | **none**                                                         | 014 §6   | `6.10`   |  **0** |
| 5   | Unknown pages   | `16:830`   | [`unknown-pages.html`](../design/mockups/unknown-pages.html)     | 004      | `4.8`    |      5 |
| 6   | Run monitor     | `16:509`   | [`run-monitor.html`](../design/mockups/run-monitor.html)         | 002, 009 | `3.16`   |      6 |
| 7   | Runs history    | `19:1344`  | [`runs-history.html`](../design/mockups/runs-history.html)       | 009      | `3.17`   |      6 |
| 8   | Products        | `18:753`   | [`products.html`](../design/mockups/products.html)               | 001, 003 | `3.18`   |      5 |
| 9   | Reports         | `18:1032`  | [`reports.html`](../design/mockups/reports.html)                 | 009      | `5.8`    |      5 |
| 10  | Authoring chat  | `24:1349`  | [`authoring-chat.html`](../design/mockups/authoring-chat.html)   | 007, 013 | `4.12`   |      5 |
| 0   | Foundations     | `8:2` ᶠ    | [`foundations.html`](../design/mockups/foundations.html)         | —        | `0.x`    |      1 |
| 11  | **Schedules**   | **none**   | **none**                                                         | 011      | `3.11`   |  **0** |

ᶠ on page `🎨 Foundations` (`3:137`), not `🖥 Screens`.

**Two rows are open defects, deliberately left visible.**

- **Screen 4's Skeleton mode is drawn nowhere.** `UI_STATES.md` §4 gives
  screen 4 three modes and spec 014 §6 makes Skeleton the escape hatch for
  content behind a click. It is `6.10` work, so being unbuilt is correct;
  being **undrawn** means `6.10` has no reference and will invent one.
- **The Schedules screen has a complete backend and no design at all.** Spec
  011 specifies it properly — `ui.schedules` and `ui.schedule_fires` (§1), the
  once-only fire loop (§3), six endpoints (§4) and five acceptance criteria.
  `3.11` builds the screen. But there is **no section in this file, no mockup,
  no Figma frame and no row in `UI_STATES.md` §4** — so of the eleven screens
  phase 3 and 4 build, ten are drawn and one is not designed at all.
  (Spec 002 is the crawl politeness scheduler and is unrelated.)
  **Design it or defer `3.11` before phase 3 starts.** A screen built with no
  state matrix is the exact failure `UI_STATES.md` exists to prevent, and this
  is the only screen in the project without one.

## State coverage

Which states each screen is drawn in. The rule is `UI_STATES.md` §1: all four
mandatory states everywhere, both empty sub-cases on screens 1 · 5 · 7 · 8,
partial on 1 · 6 · 7 · 9, dark on one screen per visual pattern (1 · 4 · 6 ·
10). **Figma matches that rule exactly — no gaps, no extras.**

| #   | pop. | loading | empty (first) | empty (filtered) | error | partial | dark |
| --- | :--: | :-----: | :-----------: | :--------------: | :---: | :-----: | :--: |
| 1   |  ✓   |    ✓    |       ✓       |        ✓         |   ✓   |    ✓    |  ✓   |
| 2   |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    —    |  —   |
| 3   |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    —    |  —   |
| 4   |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    —    |  ✓   |
| 4·S |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    —    |  —   |
| 5   |  ✓   |    ✓    |       ✓       |        ✓         |   ✓   |    —    |  —   |
| 6   |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    ✓    |  ✓   |
| 7   |  ✓   |    ✓    |       ✓       |        ✓         |   ✓   |    ✓    |  —   |
| 8   |  ✓   |    ✓    |       ✓       |        ✓         |   ✓   |    —    |  —   |
| 9   |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    ✓    |  —   |
| 10  |  ✓   |    ✓    |       ✓       |        —         |   ✓   |    —    |  ✓   |

A dash is "not required by §1", not "missing". The per-screen states beyond
these four — SSE reconnecting, snapshot expired, field multi-match and the
rest — are in `UI_STATES.md` §4 and are **not** separate frames.

## Reading order, and who wins

Three documents, three axes, no overlap (ADR-0031):

| Artifact                | Authoritative for                                           |
| ----------------------- | ----------------------------------------------------------- |
| **this file**           | which screens exist · their count · where each is drawn     |
| **Figma `🖥 Screens`**   | what every state looks like — layout, spacing, type, colour |
| **`docs/UI_STATES.md`** | which states must exist and what each must not do           |

`design/mockups/` is a **runnable reference, not an authority.** It renders in
a browser with the real tokens and no Figma account, which is why it stays;
it shows only the populated state, which is why it no longer decides
anything. Where it and Figma disagree, Figma wins.

**Reading Figma: never trust a bare `get_metadata` for an inventory.** It
reports only the pages currently loaded in the editor, so it answered "two
pages" and "four pages" to the same file on the same day. Enumerate with the
Plugin API instead — `figma.root.children` — and see ADR-0031 §Consequences.

Below, each screen's purpose and behaviour. The order is how often you will
see a screen, not navigation order.

---

## 1 · Domains — the home screen

**Answers:** what is set up, what is healthy, what needs me.

**Layout:** six-counter summary strip, then a filterable table.

_Summary strip_ — Active · Awaiting review · Broken · Paused · Never crawled ·
Pages extracted. Each counter is a **link that filters the table**, not
decoration: every number here is a question you will want to answer by looking
at the rows behind it.

_Table columns:_ Host · State · Templates · Pages · Last crawled · Extraction
health (7-day rolling pass rate, as a sparkline) · Crawl delay · Render mode · Actions.

**Default sort: extraction health ascending.** The healthy domains need nothing
from you; the degrading ones are why you opened the screen. A domain sliding
from 98% to 71% over a week is the single most valuable signal this system
produces, and it belongs at the top of the first screen.

_Bulk actions_ on selection: pause, resume, set delay, start a run over the selection.

---

## 2 · Domain detail

Four tabs.

- **Overview** — crawl delay, asset concurrency, render mode, max depth, URL caps,
  deny patterns, user-agent override. Plus `robots.txt` as fetched, with any
  `Crawl-delay` highlighted and a note on whether it overrode your configured value.
- **Templates** — every version for this domain with URL pattern, field count,
  active flag, approval date. **Diff between any two versions** — what you reach
  for when extraction breaks after a redesign.
- **Pages** — all known URLs with last observation status, filterable by validation state.
- **Activity** — chronological log: crawls, state transitions, backoff events,
  approvals. The forensic trail when a domain gets blocked and you want to know
  what the crawler did in the preceding hour.

---

## 3 · Seeds

Two modes on one screen, sharing a preview panel.

**Single URL** — paste a URL; the app resolves the host, shows whether the domain
already exists and in what state, and lets you set depth, pattern scope, and
whether this is a listing page or a direct product URL.

**CSV upload** — drag-and-drop against a fixed template:
`url, domain_hint, category, max_depth, notes`.

**The preview step is not optional.** After parsing, a table of rows with per-row
validation — malformed URL, duplicate, host already paused, depth above cap — and
a count of what would be accepted. Nothing enqueues until you confirm.

A downloadable template CSV lives on this screen. You will use it a handful of
times a month and will not remember the format.

---

## 4 · Template review — the critical screen

**This is the bottleneck made visible.** You will spend more time here than on
every other screen combined, and its design determines whether 1,200 domains is
achievable. Build it properly in phase 3, when it still only holds hand-written
selectors.

**Three panes:**

_Left (45%) — page view, three modes._ A segmented control: **Preview ·
Select · Skeleton**.

- **Preview** — a full-page screenshot from the render sidecar with a
  coordinate overlay. Hovering a selector in the centre pane outlines every
  element it matches, drawn on the overlay.
- **Select** — the visual playground (spec 014). Hover highlights the smallest
  element under the cursor, `[` / `]` walk the ancestor chain, and a click
  assigns that element to the selected field. The proposed selector appears
  immediately with **every** match highlighted, so six boxes where you
  expected one is instant feedback.
- **Skeleton** — what the model actually saw, node indices visible and
  clickable. This tells you whether a wrong proposal was misled or just
  mistaken, and it is the escape hatch for content hidden behind a click.

**There is no iframe.** The pane is a screenshot plus a geometry list from
`POST /inspect`, so no supplier HTML or script ever enters the app document.
A sandboxed iframe would block the script but then render the page wrong, and
cross-origin framing gives no DOM access anyway — which was the whole point.
Spec 014 §1 covers the trade-off; the cost is that hover states and
click-to-open content need the `expand` option or Skeleton mode.

**Why the playground is a mode and not an eleventh screen.** Clicking a price is
one way to fill the same field list the centre pane already shows, verified
against the same sample strip. Splitting it out would mean two screens
competing to own one draft, two copies of the field list, and a hand-off
between them in the middle of the only task that matters here.

It is nonetheless drawn as its own top-level artifact — Figma `27:1548`
(`Playground — Select mode`) and `design/mockups/playground.html` — because
the three-pane Select layout is too different to be a variant of the Preview
frame. Registry rows `4`, `4·S` and `4·K` carry the mapping. **Skeleton mode
is drawn nowhere**; `6.10` builds it and currently has no reference.

_Centre (35%) — field list._ One `<SelectorField>` per field: name · editable
selector · **resolved value on this page** · match count · model confidence.
Edits re-resolve on a 300 ms debounce against the already-loaded DOM, with no
network round-trip.

_Right (20%) — sample strip._ Three to five URLs from the same pattern with a
per-field pass/fail grid.

**The sample strip is the feature that makes this screen worth building.** A
selector that works on the page in front of you and fails on the next product is
the single most common error, and it is invisible in a one-page review. A cell
turns red the moment a selector stops resolving on any sample, before you approve
anything.

_Field controls:_ validation rule (currency, non-empty, URL,
integer, date) · transform chain (trim, strip currency symbol, resolve relative
There is no required/optional control: no field is ever required (ADR-0027),
so the screen has nothing to offer there.
URL, first vs. all) · fallback selector.

**Discovery rules live on the same screen** — `next_page`, `product_link`,
`subcategory_link`, depth cap, allow/deny patterns. A **dry-run discovery**
button crawls one listing page and shows exactly which URLs would be enqueued,
grouped by the rule that matched. This is where you catch a faceted-navigation
trap before it generates 40,000 URLs, and it is far cheaper than catching it
mid-run.

**Batch mode ships with this screen, not after it.** A grid of up to 20 templates,
each collapsed to resolved values, approve/reject per row, one confirm. The
single view and the grid are **two renderings of the same review state**, not two
screens: both read the same verified-proposal payload, and "open full review"
expands a row in place. Built this way it costs little; retrofitted later it means
reworking state management rather than adding a view.

---

## 5 · Unknown pages

Pages that could not be understood. Your work queue.

**Grouped, not listed.** A flat list of 400 failures is useless; the same root
cause usually produces dozens. Group by `(domain, failure_reason, url_pattern)`
so one fix clears the group.

| Reason               | Meaning                              | Action offered                                                                                                                                                                                  |
| -------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no_template`        | No template matches this URL pattern | Propose a template                                                                                                                                                                              |
| `fetch_error`        | Non-2xx or timeout                   | Retry, or inspect the response                                                                                                                                                                  |
| `empty_extraction`   | 200, nothing resolved                | **Diff against the last working observation when there is one — that is a redesign. When there is none the page never worked: a dead link or a layout the template does not cover (ADR-0030).** |
| `llm_low_confidence` | Proposal below threshold             | Review manually                                                                                                                                                                                 |

_Row expansion_ shows the stored HTML snapshot (within its 7-day TTL), the
template attempted, and per-field failure detail.

**An `empty_extraction` row says whether the page ever worked**, because that
is what separates a redesign from a dead link and it is the first thing the
operator needs (ADR-0030). It is also what decides whether the page counted
toward the domain's `broken` threshold, so the inbox and the state have to
agree. `validation_failed` is not in this table: nothing is required, so a
field failing its rule is recorded on the observation and routes nothing
(ADR-0027).

**Dismiss-as-not-a-product-page adds a deny pattern to the domain.** Without
that path the same URLs reappear every run and the inbox slowly becomes noise
you stop reading.

---

## 6 · Run monitor

SSE-driven. What is happening right now.

**Header:** run ID, elapsed, Pause / Stop, and an overall stacked `<ProgressBar>`.

**Per-domain cards:** host · state · own progress bar · pages/min · current delay
(flagged if backoff raised it) · error count · next-eligible countdown. **An
auto-paused domain goes red and sorts to the top.**

**Two throughput lines on one axis — pages/min and assets/min.** They should look
different. Seeing them diverge is how you confirm the two pools are independent:
a flat page line with a climbing asset line is normal after discovery finishes;
the reverse means the asset pool is starved or a host is throttling.

**Asset pool panel:** queue depth, in-flight count, per-host concurrency in use,
dedupe hit rate. Queue depth climbing steadily is the backpressure signal, and it
belongs on screen rather than in a log.

**Live log pane:** timestamp · domain · URL · status · winning extraction strategy
· field count. Filterable, pausable.

**Reconnection is non-negotiable.** The browser will sleep and you will close the
laptop. SSE reconnects with `Last-Event-ID` and the UI backfills from the run's
event log rather than showing a gap or a frozen bar that looks like a stall.

---

## 7 · Runs history

Completed runs, newest first: run ID · started/duration · domains · pages ·
changed · new · failures · assets · bytes.

_Run detail_ expands to per-domain breakdown, validation summary, failing pages,
and a **diff against the previous run of the same domain set** — the view that
answers "did this redesign break us, or did we always have 12% failures here."

_Comparison mode:_ select two runs → side-by-side counts and the domains whose
health moved materially.

---

## 8 · Products

Browse what was extracted. Filters: domain · category · validation state ·
last-seen window · price range · has-images · free text.

_Table view_ for scanning; _card view_ with thumbnails for visual verification —
the fastest way to spot that a selector has started picking up a placeholder or a
related-product image.

**Product detail** is where change tracking surfaces: current fields with
validation badges, observation timeline, price history chart, field-level diff
between any two observations, the image set with dedupe indication, and the
source URL.

**Each observation records the template version that produced it.** That is what
lets you attribute a data change to a site change rather than to your own edit.
Without it, a price history containing your own selector mistake is
indistinguishable from a real price move.

---

## 9 · Reports

Standing reports, not ad-hoc querying. Each is a saved view with CSV and JSON export.

- **Extraction health** — pass rate by domain and field, trended. The entry point
  for finding silent breakage.
- **Broken templates** — domains over the 20% threshold, with the first bad run and
  the field that degraded first.
- **Price changes** — filterable by magnitude so ±1% noise can be ignored.
- **New and disappeared products** — appeared this run, or absent for N runs.
- **Crawl politeness** — requests per domain, 429/403 counts, average effective
  delay. Your evidence the crawler behaved, and the first place to look after a block.
- **Coverage** — domains onboarded, templates approved, backlog over time.

**The coverage report is the one to build last and read most.** Onboarding pace
against backlog growth is the number that tells you whether the tiered-coverage
mitigation is needed yet, or still just an option.

---

## 10 · Authoring chat

**Where a template starts when you have no idea what the page contains.**
Reached from Domain detail or from a seed: paste one to five URLs, describe
what you want in plain language, and watch a draft fill in.

**Two panes:**

_Left (35%) — conversation._ Your instructions and the system's replies.
Each reply is a short statement of what it did, not prose: _"fetched 3 pages ·
proposed 7 fields · 5 verified · `lead_time` found on 1 of 3."_ Streamed over
SSE (ADR-0012), same transport as run progress.

_Right (65%) — the draft, live._ The same field list and sample strip as
screen 4, filling in as candidates verify. Each field shows its provenance
badge — **form · chat · clicked** — because knowing a selector came from a
model rather than from a click changes how hard you look at it.

**The chat produces a template, never data.** Asking it for "the price on
these pages" yields a verified selector and the value it resolves to on each
sample, not a table of extracted prices. Per-page LLM extraction through the
back door is exactly what ADR-0005 rejects.

**Visible limits, not hidden ones.** A footer shows `3 / 5 sample pages used`.
Asking for a sixth, for another domain, or for a run to start is refused with
a one-line reason — the politeness model has no exceptions for interactive
work, and a chat that quietly fetches twenty pages would be the rudest thing
in the system.

**"Open in review"** hands the draft to screen 4 with every field, example and
transcript entry intact. The two screens are two front doors to one draft
(ADR-0019), so there is nothing to migrate.

---

## 0 · Foundations

Not a product screen — the design system rendered as a page, so colour, type,
logo and components can be reviewed in both themes without reading CSS.
