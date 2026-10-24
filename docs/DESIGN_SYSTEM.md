# Spydra — design system

A single-operator control room, not a consumer app. Density beats whitespace,
every list is filterable, and every state is visible without drilling in. You
are the only user and you will be looking for problems, so the interface
surfaces anomalies rather than celebrating successes.

**Authority:** this file owns the tokens. The **Figma file**
(`GeJPFXY4CicHBdzLMyXG2E`) owns what screens and states look like,
[`SCREENS.md`](SCREENS.md) owns which screens exist, and
[`COMPONENTS.md`](COMPONENTS.md) records what the Figma library contains
(ADR-0031). `design/mockups/` below is a **runnable reference, not an
authority** — populated-state only, and Figma wins where they disagree.

**Reference implementation:** [`design/mockups/`](../design/mockups/) — open
`index.html` from disk, no build step. Every class in `assets/app.css` maps to
a component named below.

---

## The one rule

**Colour carries state. Nothing else.**

Brand indigo is for actions, focus and active navigation. The six lifecycle
colours mean domain state. Everything else is neutral. If everything is
coloured, the one red row stops registering — and finding that row is the
entire job.

This is enforced structurally, not by discipline:
`design/tokens/tailwind-theme.css` sets `--color-*: initial` before
declaring the semantic set, so `text-red-600` in a component fails to
compile. Components consume semantic utilities (`text-state-broken`,
`bg-surface`) or they do not build.

---

## Tokens

Declared once in [`design/tokens/tokens.css`](../design/tokens/tokens.css),
mirrored in `tokens.json` (W3C format, for Figma and other tooling), exposed
to Tailwind v4 by
[`design/tokens/tailwind-theme.css`](../design/tokens/tailwind-theme.css).

**`tokens.css` is canonical; the other two follow it.** The direction matters
because two of the three are easy to forget:

- `tailwind-theme.css` must map a new token into `--color-*` / `--spacing-*`
  or it generates no utility, and `bg-skeleton` then paints nothing — it
  compiles, resolves to an undefined `var()`, and fails silently. That was
  true of the skeleton, overlay and disabled tokens for four commits.
- `tokens.json` is a **curated light-theme subset**, not a 1:1 copy: literal
  hex, no aliases, no dark extension, no `-bg` tints. It exists for Figma and
  other tooling, nothing in the build reads it, and nothing checks it is in
  step. A token that a Figma frame needs has to be added here by hand.

**Every token is prefixed `--sp-*`.** Tailwind v4 claims `--color-*`,
`--text-*`, `--font-*`, `--radius-*`, `--shadow-*`, `--leading-*`,
`--tracking-*` and `--ease-*` as theme namespaces; an unprefixed
`--text-primary` would be silently read as a font size (ADR-0018). Do not
remove the prefix.

### Utility reference

| Need              | Class                                      |
| ----------------- | ------------------------------------------ |
| App background    | `bg-canvas`                                |
| Card / panel      | `bg-surface border border-line rounded-lg` |
| Table header      | `bg-subtle`                                |
| Body text         | `text-ink`                                 |
| Secondary text    | `text-ink-muted`                           |
| Metadata          | `text-ink-subtle`                          |
| Primary button    | `bg-brand text-white hover:bg-brand-hover` |
| Active nav item   | `bg-selected text-ink-brand`               |
| Broken state pill | `bg-state-broken-tint text-state-broken`   |
| Focus ring        | `ring-2 ring-focus ring-offset-2`          |
| Chart series      | `stroke-viz-1` … `stroke-viz-6`            |

### Theme

**Light is the default.** A persistent toggle sits in the top bar. On a first
visit the app respects `prefers-color-scheme`; once the user chooses, that
choice is stored in `localStorage` and wins on every later load.

Theme resolution runs in an inline script in `<head>`, before first paint, so
dark never flashes white on load. Every `localStorage` access is wrapped in
try/catch — it throws in a private window and the app must still render.

### Lifecycle colour

| State        | Light     | Dark      | Meaning                     |
| ------------ | --------- | --------- | --------------------------- |
| `discovered` | `#6B7280` | `#9CA3AF` | Seeded, nothing known       |
| `pending`    | `#B45309` | `#F59E0B` | Awaiting your approval      |
| `active`     | `#047857` | `#34D399` | Approved template, crawling |
| `broken`     | `#B91C1C` | `#F87171` | Failures over threshold     |
| `paused`     | `#C2410C` | `#FB923C` | Stopped deliberately        |
| `archived`   | `#9CA3AF` | `#6E7684` | Retired, data retained      |

Hues are identical across themes; only lightness shifts. The mapping a user
learns in one theme still holds in the other. Both themes are checked against
WCAG AA for body text and AAA for state pills — the elements read fastest and
most often.

### Typography

| Role        | Face                       | Notes                                                |
| ----------- | -------------------------- | ---------------------------------------------------- |
| UI          | **Inter** (variable)       | Neutral, excellent at 13–14 px, true tabular figures |
| Data / code | **JetBrains Mono**         | Selectors, URLs, JSON, log lines                     |
| Wordmark    | **Space Grotesk** 500, −2% | Logo only — never in the interface                   |

**Self-host both UI families.** This is a local tool that must work with the
network down, and a font request would be the only outbound call the UI makes.
The mockups link the Google Fonts CDN for convenience; production does not.

**Base 14 px.** This is a dense operational interface; 16 px wastes a third of
every table row.

```
11/16  table micro-labels, badges, uppercase +0.04em
12/18  secondary metadata, timestamps, helper text
13/20  table body, dense lists
14/22  body default, form inputs
16/24  card titles
20/28  screen headings
28/36  page titles (sparing)
```

Weights: 400 body, 500 table headers and labels, 600 headings. Nothing lighter
than 400, nothing heavier than 600.

**Rules that matter in this UI specifically:**

- `font-variant-numeric: tabular-nums` on **every** numeric column. SSE updates
  land continuously and proportional digits make the whole table shiver.
- Monospace for every selector, URL and field value in the review screen. A CSS
  selector in a proportional face is harder to read character by character, and
  character-level reading is exactly what that screen asks of you.
- URLs truncate in the **middle** — the path tail is the distinguishing part.
- Numbers and identifiers never wrap; long text clamps to two lines with a tooltip.

### Space, form, motion

- **4 px base unit**, component padding on an 8 px rhythm.
- Table rows 36 px comfortable / 28 px compact, user-toggleable and persisted.
- **Radius:** 6 px controls, 8 px cards, 4 px badges, full-round on status dots only.
- **Borders over shadows.** A 1 px border separates surfaces; elevation is reserved
  for genuinely floating things — dropdowns, popovers, the one modal. Flat bordered
  surfaces read as precise; shadows everywhere read as a consumer app.
- **Focus:** 2 px brand ring, 2 px offset, on every interactive element. The review
  screen is operated from the keyboard more than the mouse.
- **Motion:** 120–160 ms ease-out on state changes, none on data updates. A row whose
  value changed gets one 400 ms background flash, then settles. Nothing slides,
  nothing bounces. All motion respects `prefers-reduced-motion`.

---

## Components

Shared widgets, built once and composed everywhere. In the mockups these are CSS
classes; in the React app they are the components named here.

### The coded library (`3.9`)

Thirty-one components in `frontend/src/components/`, one file per component:
props in, markup out, no fetching (spec 006 §1). Variant axes follow
`UI_STATES.md` §3 against the Figma library re-measured in
[`COMPONENTS.md`](COMPONENTS.md); the first line of each file names its Figma
component. Hover, focus and pressed arms are `hover:` / `focus-visible:` /
`active:` utilities, not
props — a prop that says "hover" would fight the browser's own hover. Ephemeral
state (spinner, skeleton) consumes the skeleton/disabled token pairs; every
persistent state is a prop.

**§3a — atoms and controls (14)**

| Component           | Figma (node)            | Variants / props                                                                                                                                                                     |
| ------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `<Button>`          | Button                  | `variant=` primary · secondary · ghost · danger × `size=` sm · md; `loading` — spinner joins the held label so the width never moves                                                 |
| `<Input>`           | Input `42:156`          | `error` · `prefix` · `onClear` over native `value`/`disabled`/`readOnly`; focus ring lands on the wrapper (`focus-within`)                                                           |
| `<Card>`            | Card                    | `interactive` (hover border) · `selected` (border-focus + bg-selected) · `loading` (content swaps for a skeleton)                                                                    |
| `<Tag>`             | Tag `43:146`            | `tone=` neutral · info · success · warning · danger × `removable` × `disabled` — tones map to feedback semantics                                                                     |
| `<ProgressBar>`     | Progress bar `43:270`   | `segments={queued,inFlight,done,failed}` stacked (in-flight is `viz-1`) or `state=` running · paused · complete · failed · empty + `fraction`; optional `legend`; never a percentage |
| `<Tabs>`            | Tab `10:100`            | `items {id,label,count?,disabled?}` × `value`; count badge is a `tabular-nums` pill; within-screen only, never navigation                                                            |
| `<StatePill>`       | State pill              | `state=` the six lifecycle states + `why` tooltip; dot + label on the state tint pair                                                                                                |
| `<MetricTile>`      | Metric tile `11:71`     | `value: number \| null` — **null is the unavailable tile** (em dash, the partial-counter contract); `loading` swaps in a skeleton; `tone=` default · attention · danger              |
| `<Banner>`          | Banner `11:84`          | `tone=` info · warning · danger × `action` × `dismissible`                                                                                                                           |
| `<SelectorField>`   | Selector field `11:142` | state derived from `matches: number \| null` (null resolving · 0 no-match, muted · >1 warning) + `invalid` · `disabled`; mono selector over a resolved sample value                  |
| `<Confidence>`      | Confidence              | `level=` high · good · medium · low; lit bars 4→1 carry the signal, band colour active/pending/broken                                                                                |
| `<ValidationBadge>` | Validation badge        | `kind=` pass · partial · fail × `count` · `rule` (tooltip names the failing rule)                                                                                                    |
| `<SampleCell>`      | Sample cell `10:83`     | `result=` pass · fail · partial · pending — pending is a neutral dash, not an error                                                                                                  |
| `<Sparkline>`       | Sparkline `10:93`       | `trend=` healthy · slipping · failing · pending × `values` (empty draws the flat pending line); hand-written SVG                                                                     |

**§3b — shared sets (17)**

| Component           | Figma (node)               | Variants / props                                                                                                                                                                                       |
| ------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `<TableHeaderCell>` | Table header cell          | `sort=` none · asc · desc (`aria-sort`) with the sort control a button in `<th>`; sortable when `onSort` is passed                                                                                     |
| `<RowActionMenu>`   | Row action menu `199:1306` | `open` × per-item `danger` / `disabled`; the screen owns open state and outside-click dismissal                                                                                                        |
| `<FilterChip>`      | Filter chip `199:1316`     | `active` · `removable` · `onClick`                                                                                                                                                                     |
| `<SearchField>`     | Search field `199:1339`    | empty / typing / with-clear derived from `value`; the `noResults` arm is a prop                                                                                                                        |
| `<BulkActionBar>`   | Bulk action bar `199:1294` | `count` — 0 unmounts (hidden); visible is count + `actions` + clear                                                                                                                                    |
| `<Checkbox>`        | Checkbox                   | `checked` true · false · `"indeterminate"` (`aria-checked="mixed"`; a button, because the DOM property is not static markup) × `disabled`                                                              |
| `<Pagination>`      | Pagination `196:1332`      | first / last / single-page **derived** from `page` × `pageCount`; ghosted chevrons at the ends, summary optional                                                                                       |
| `<Select>`          | Select `51:293`            | `open` · `error` · `disabled` × with-value / placeholder derived; a custom listbox (a native select cannot express the open or error arms)                                                             |
| `<Toggle>`          | Toggle `51:303`            | `checked` × `disabled`; `role="switch"`                                                                                                                                                                |
| `<Skeleton>`        | Skeleton `33:120`          | `shape=` row · card · chart · pane · text-line; row is `h-row-comfortable` from the spacing token (test-asserted); card/chart/pane place children at fractional offsets so resizing never overflows    |
| `<Spinner>`         | Spinner                    | `size=` sm · md × `onBrand` — `brand-subtle` is the constant on-brand ink (`text-inverse` flips per theme)                                                                                             |
| `<EmptyState>`      | Empty state                | `kind=` first-run · filtered · no-results (icon + title + body + action; first-run's action is primary, filtered never offers to create)                                                               |
| `<ErrorState>`      | Error state                | `kind=` fetch · permission · timeout · partial × `reason` + retry — never strands the user                                                                                                             |
| `<Toast>`           | Toast `34:201`             | `tone=` info · success · warning · danger × `action` × `dismissible`; danger is `role="alert"`, the rest polite status                                                                                 |
| `<Modal>`           | Modal `201:1381`           | `kind=` confirm · confirm-danger · form · wide × `submitting` (confirm goes loading, label held). **Dialog card only, no scrim** — no token-legal scrim colour exists; the screen dims its own surface |
| `<Tooltip>`         | Tooltip `201:1406`         | `side=` top · bottom · left · right                                                                                                                                                                    |
| `<LineChart>`       | Line chart `201:1489`      | 1–2 series on `viz-1`/`viz-2` × `live` (pulse on the last point); no-data derived from empty series; Recharts arrives with the first screen that needs axes                                            |

There is deliberately **no generic table-row component**: Figma's `Table row`
was deleted (hard-wired to one column set) and the six concrete rows land with
their screens (`COMPONENTS.md` §3) — the shared deliverable here is
`<Skeleton shape="row">` over `--sp-row-comfortable` / `--sp-row-compact`.
`Icon` was not coded: Empty/Error/Toast carry their own inline glyphs, and a
13-glyph component with one consumer would be inventory, not reuse. Sidebar and
Topbar variants are 3.8's `AppShell`, not this library.

### Named ahead of their screens

Reference implementations exist in the mockups; the React components land with
the screen that first needs them.

| Component               | Class            | Behaviour                                                                                                                                                            |
| ----------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<PagePreview>`         | `.preview-frame` | Screenshot + overlay canvas; active selector's matches outlined in place. No iframe — spec 014 §1                                                                    |
| `<ObservationTimeline>` | —                | Time series with change points and template-version markers                                                                                                          |
| `<DataTable>`           | `.table-wrap`    | Server-side pagination, column filters, URL-encoded state                                                                                                            |
| `<SampleMatrix>`        | `.sample-grid`   | Per-field pass/fail across sample URLs (composes `<SampleCell>`)                                                                                                     |
| `<ProvenanceBadge>`     | `.prov`          | Where a selector came from — form · chat · clicked · escalated                                                                                                       |
| `<SelectionOverlay>`    | `.sel-box`       | Absolutely positioned boxes over the screenshot: hovered, picked, other matches, container. Translucent, never opaque — they sit **over** the content being selected |
| `<AncestryBar>`         | `.ancestry`      | The clicked node's ancestor chain; `[` / `]` walk it, rejected classes struck through                                                                                |
| `<FieldVocabulary>`     | `.vocab`         | The canonical field list a click assigns to                                                                                                                          |
| `<ChatMessage>`         | `.msg`           | Operator / system / refusal, with the terse mono variant for what the system did                                                                                     |

### Three decisions worth keeping

**`<ProgressBar>` shows a stacked bar, not a percentage.** During discovery the
denominator is still growing, so a percentage would simply lie.

**`<SelectionOverlay>` tints are translucent.** An opaque fill hides the very
element being selected — and the first build of the mockup did exactly that,
which is why it is written down here rather than left to taste.

**`<DataTable>` keeps filter state in the URL.** When a run surfaces 40 broken
pages you want to send yourself that exact filtered view, not reconstruct it.

---

## App shell

Persistent 240 px sidebar, collapsible to icons. No modals for anything taking
longer than a second — long operations get their own route so a refresh does not
lose them.

**Two live badges in the sidebar, both SSE-fed:** pending reviews (amber) and
active run (green pulse with page counter). They exist because the two things
that silently stall this system are an unreviewed template queue and a dead
`llama-server`. Both must be visible from every screen without navigating.

**Sidebar footer:** `llama-server` reachability, Postgres, free disk on `/data`.

---

## Anti-patterns

Named explicitly, because crawler tooling drifts toward them by default:

- Terminal aesthetics — monospace everywhere, green-on-black, ASCII borders, scanlines
- Neon accents, glow, glassmorphism, animated gradient backgrounds
- Dark-mode-only, or a dark mode that is the light theme inverted
- Decorative spider webs in the chrome. The logo carries the metaphor; the
  interface does not repeat it
- Colour used for emphasis rather than meaning
- Raw Tailwind palette classes in components (the theme makes these fail to build)
- Removing the `--sp-*` token prefix (it is what prevents a silent Tailwind namespace collision)
