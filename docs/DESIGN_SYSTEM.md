# Spydra — design system

A single-operator control room, not a consumer app. Density beats whitespace,
every list is filterable, and every state is visible without drilling in. You
are the only user and you will be looking for problems, so the interface
surfaces anomalies rather than celebrating successes.

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

| Component               | Class             | Behaviour                                                                                                                                                            |
| ----------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<DomainStatePill>`     | `.pill`           | Lifecycle state, dot + label, tooltip explains why                                                                                                                   |
| `<SelectorField>`       | `.selector-field` | Editable selector + live resolved value + match count. Red when it resolves to nothing, amber when it resolves to several                                            |
| `<PagePreview>`         | `.preview-frame`  | Screenshot + overlay canvas; active selector's matches outlined in place. No iframe — spec 014 §1                                                                    |
| `<ValidationBadge>`     | `.pill` + count   | Per-field pass/fail with the failing rule named                                                                                                                      |
| `<ProgressBar>`         | `.progress`       | Queued / in-flight / done / failed as a **stacked bar, never a percentage**                                                                                          |
| `<Sparkline>`           | `.spark`          | 7-day health trend, coloured by band                                                                                                                                 |
| `<ObservationTimeline>` | —                 | Time series with change points and template-version markers                                                                                                          |
| `<DataTable>`           | `.table-wrap`     | Server-side pagination, column filters, URL-encoded state                                                                                                            |
| `<Confidence>`          | `.confidence`     | Four-bar model confidence, coloured by band                                                                                                                          |
| `<SampleMatrix>`        | `.sample-grid`    | Per-field pass/fail across sample URLs                                                                                                                               |
| `<Banner>`              | `.banner`         | Info / warn / danger, with inline actions                                                                                                                            |
| `<ProvenanceBadge>`     | `.prov`           | Where a selector came from — form · chat · clicked · escalated                                                                                                       |
| `<SelectionOverlay>`    | `.sel-box`        | Absolutely positioned boxes over the screenshot: hovered, picked, other matches, container. Translucent, never opaque — they sit **over** the content being selected |
| `<AncestryBar>`         | `.ancestry`       | The clicked node's ancestor chain; `[` / `]` walk it, rejected classes struck through                                                                                |
| `<FieldVocabulary>`     | `.vocab`          | The canonical field list a click assigns to                                                                                                                          |
| `<ChatMessage>`         | `.msg`            | Operator / system / refusal, with the terse mono variant for what the system did                                                                                     |

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
