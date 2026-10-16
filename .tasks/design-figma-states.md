# design/figma-states

**Task:** bring the Figma file up to `docs/UI_STATES.md`
**Spec:** `docs/UI_STATES.md` · **Screens:** `docs/SCREENS.md` · **Tokens:** `design/tokens/tokens.css`
**ADRs that constrain this:** 0018 (React 19 + Tailwind 4), 0019 (one pipeline, three front doors), spec 014 §1 (no iframe)

File: `GeJPFXY4CicHBdzLMyXG2E` ("SpiderUI"). Pages: Cover · 🎨 Foundations · 🧩 Components · 🖥 Screens.

## Where this started

The file had all 11 screens in their **populated state only**, 28 component
sets, and **no prototype**. `Skeleton`, `Spinner`, `Empty state`, `Error
state`, `Toast`, `Checkbox`, `Table header cell`, `Table row` and `Card`
existed but were instanced by **zero** screens — the library was built to a
checklist and the screens were built separately, so they never met.

`docs/UI_STATES.md` was written after that work began and is now the
authority. Some of what is already in the file predates it and does not match
— see _Deltas_ below before building anything else.

## Done

**Component sets added** — Icon (13 glyphs) · Nav item (6) · Segmented control
(3) · Kbd (4) · Chat message (3) · Log row (3) · Domain card (3) · Screenshot
viewport (4) · Select (4) · Toggle (3) · Pagination (1).

**Component sets extended** — Button 8 → **48** (`Style` × `Size` × `State`:
default · hover · active · focus · disabled · loading, loading width frozen to
its Default twin) · Input 1 → **10** (`State` × `Content`) · Tag 1 → 5 · Card
1 → 4 · Progress bar 1 → 5.

**Screens** — 30 frames. The 11 populated originals, `— Loading` for all 11,
and `— Empty` / `— Error` for the four risk-weighted screens (Template
review, Run monitor, Authoring chat, Playground). Each state frame keeps the
real chrome and replaces only `Main > Content`.

**Prototype** — 261 sidebar navigation links across every frame, 11
after-delay loading → populated transitions (1.2 s), 4 retry buttons on the
error frames looping back through loading. Three flow starting points:
_Spydra — operate_, _Cold start_, _Template review — the bottleneck_.

**Two defects fixed in the file itself:**

1. **16 Color variables lacked the `FRAME_FILL` scope** — `brand/action`,
   `brand/action-hover`, all six `state/*`, all six `viz/*`, `feedback/info`,
   `overlay/outline`. Binding one to a frame recorded silently and never
   rendered. This is worth knowing for the React side too: a token can look
   bound in Figma and not be.
2. The sidebar reported **`postgres 17.2`**; the stack is 18.

## Deltas against UI_STATES.md — read before continuing

Built before the spec existed, and **wrong against it**:

- **`Tag`** was given a `Tone` axis (neutral/info/success/warning/danger).
  UI_STATES §3a asks for **removable · disabled**. Colour already belongs to
  `State pill`; the Tone axis probably has to go.
- **`Log row`** uses `Status=Ok|Failed|Skipped`. The spec says **`Status=` ok ·
  warn · error × `Strategy=` structured · selector · llm · none**.
- **`Chat message`** uses `Role=User|System|Refusal`. The spec says **`From=`
  user · system × `Kind=` statement · refusal · error · streaming**.
- **`Screenshot viewport`** bundles the overlays into the pane. The spec wants
  a standalone **`Selection overlay`** (hover · selected · match ·
  multi-match-warning). Overlay opacities are now 12 / 20 / 14 % per the new
  tokens, but the decomposition still differs.
- **`Kbd`** is one variant per key; the spec wants **`Keycap`: single · pair**.
- **`Pagination`** is a single static component; the spec wants default ·
  first-page · last-page · single-page.
- **`Select`** has no `error` state and no `with-value / placeholder` axis.
- **`Domain card`**, **`Nav item`** and **`Icon`** are not in the spec's 45 at
  all. Keep or fold in deliberately, don't leave them undecided.

**Not built yet** (from §3b, roughly 20 sets): Table row skeleton · Bulk action
bar · Row action menu · Filter chip · Search field · Modal · Tooltip · Numeric
stepper · Dropzone · Validation row · Ancestor breadcrumb · Provenance badge ·
Diff row · Countdown · Line chart · Price history chart · Image thumbnail ·
Stat strip counter. Plus the §3a additions to Tab, Metric tile, Banner,
Selector field, Sample cell, Sparkline, Sidebar and Topbar.

**Screen states not built** — everything in §4 beyond loading/empty/error, and
the `Partial` state for screens 1, 6, 7 and 9. Dark mode: §4 asks for one
screen per visual pattern (1, 4, 6, 10); none exist.

**Prototype not built** — the §5 flow is only partly wired. Missing: row →
domain detail, counter → filtered → filtered-empty, Review → review loading,
the segmented-control mode switch, field click → multi-match, Approve →
submitting → toast → Domains, the Seeds dropzone sequence, and the run-monitor
reconnect loop.

## Open question for the human

`design/mockups/` was going to be retired in favour of Figma, decided before
it was clear that **phase 0 is already at task 0.13** and that `docs/specs/006-frontend.md`
still names the mockups as the UI specification. **Nothing has been deleted.**
Retiring them now means updating spec 006, `SCREENS.md`, `DESIGN_SYSTEM.md`,
`docs/README.md`, `README.md`, `WORKFLOW.md`, the `spydra-frontend` role and
the deck, and it changes what phase 3 builds against. Decide before phase 3,
not during.

## Handoff log

- design — components, state frames and prototype as above. Deltas against
  UI_STATES.md listed rather than silently reconciled, because several are
  judgement calls about which decomposition is right, not mistakes.
