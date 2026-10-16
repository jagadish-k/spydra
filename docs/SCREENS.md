# Spydra — screens

Ten screens plus a foundations page. Each is specified below and mocked up in
[`design/mockups/`](../design/mockups/).

**The mockups show each screen populated.** Every state a screen also has —
loading, empty, filtered-empty, error, partial — is in
[`UI_STATES.md`](UI_STATES.md), which is authoritative for states and binding
on the phase 3 components (ADR-0025). Read the two together: this file says
what a screen is for, the mockups say what it looks like, `UI_STATES.md` says
how many ways it has to look.

Screen 4 carries the visual playground as a _mode_, not as a separate screen —
see the note there for why.

The screens are ordered by how often you will see them, not by navigation order.

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

**Why the playground is a mode and not a tenth screen.** Clicking a price is
one way to fill the same field list the centre pane already shows, verified
against the same sample strip. Splitting it out would mean two screens
competing to own one draft, two copies of the field list, and a hand-off
between them in the middle of the only task that matters here.

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

_Field controls:_ required/optional · validation rule (currency, non-empty, URL,
integer, date) · transform chain (trim, strip currency symbol, resolve relative
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

| Reason               | Meaning                                       | Action offered                                             |
| -------------------- | --------------------------------------------- | ---------------------------------------------------------- |
| `no_template`        | No template matches this URL pattern          | Propose a template                                         |
| `validation_failed`  | Selectors resolved, values failed their rules | Open in review with this page loaded                       |
| `fetch_error`        | Non-2xx or timeout                            | Retry, or inspect the response                             |
| `empty_extraction`   | Selectors matched nothing at all              | Usually a redesign — diff against last working observation |
| `llm_low_confidence` | Proposal below threshold                      | Review manually                                            |

_Row expansion_ shows the stored HTML snapshot (within its 7-day TTL), the
template attempted, and per-field failure detail.

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
