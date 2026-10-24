# feat/3.9-design-system-components

**Task:** BUILD_PLAN 3.9 — design-system components (spec 006 §2), the first
slice of phase 3 · **Spec:** `docs/specs/006-frontend.md` §1–3 ·
**Matrix:** `docs/UI_STATES.md` §1–3 · **Catalog:** `docs/COMPONENTS.md` ·
**Tokens:** `docs/DESIGN_SYSTEM.md`
**ADRs that constrain this:** 0018 (prefixed tokens, palette fails the build),
0025 (§scope — **the two lists below are copied from it, not re-derived**),
0031 (three artifacts, one axis each; never inventory Figma with a bare
`get_metadata`), 0032 (cardinal rule — anything above a primitive is a
component; instance-only composition; property discipline)

Figma file `GeJPFXY4CicHBdzLMyXG2E`: 🧩 Components `3:138` (49 components,
230 variants, 1,761 instances), 🖥 Screens `3:139`. Enumerate per-page through
`use_figma` (`figma.root.children`), never bare `get_metadata` (ADR-0031 §7).

## Reorder — sanctioned, and why

BUILD_PLAN lists 3.8 (shell) before 3.9 (components); this slice runs first.
Sanctioned by the plan's own rule — "tasks within a phase may be reordered
where there is genuinely no dependency — but check, and say so in the task
file" — and checked: **the components are props-in/render-out with no
dependency on routing or the shell; the shell consumes them later.** Running
3.9 first means 3.8 builds `AppShell` against the completed library instead of
against variants that are still missing. `3.8` stays after `3.9`; nothing else
moves.

## Contract — this slice has two halves

### Half A — the Figma library (page `🧩 Components`)

Complete the shared variant sets **in the library**, per ADR-0025 §scope and
`COMPONENTS.md` §5 (the measured state). The lists below are the contract.

**§3a — all seventeen rows are in scope. Four are done (verify only); of the
remaining thirteen, eleven need variants and two are matrix-complete:**

Done, verify only (4): **Button** · **Card** · **State pill** · **Logo set**.

To build (11):

| #   | Component      | Add (from `UI_STATES.md` §3a)                                           |
| --- | -------------- | ----------------------------------------------------------------------- |
| 1   | Metric tile    | `State=` loaded · loading · **unavailable** — **EARLY/REQUIRED**, below |
| 2   | Input          | readonly · with-prefix · with-clear (focus · error · disabled exist)    |
| 3   | Tag            | removable · disabled (currently `Tone=` only — see Open questions)      |
| 4   | Progress bar   | **stacked** (queued / in-flight / done / failed; never a percentage)    |
| 5   | Tab            | hover · disabled · with-count-badge                                     |
| 6   | Banner         | dismissible · with-action                                               |
| 7   | Selector field | resolving · disabled · **no-match** (distinct from error)               |
| 8   | Sample cell    | `State=pending`                                                         |
| 9   | Sparkline      | `State=pending`                                                         |
| 10  | Sidebar        | expanded · collapsed (`Active=` already exists)                         |
| 11  | Topbar         | with-search-focus (`Breadcrumb` already exists)                         |

Matrix-complete, verify and record, build nothing (2): **Confidence** ·
**Validation badge**. (4 + 11 + 2 = 17.)

The first early/required item, from BUILD_PLAN 3.9 inline:
**`Metric tile State=unavailable`** — the five Partial frames already override
a `Value` to an em dash, so the component and the frames disagree until the
variant exists. Reconcile those five instances on `🖥 Screens` (the only
permitted edit to that page). The second — the size-tolerant `Skeleton` — is a
§3b set and is called out below.

**§3b — the twenty shared sets (ADR-0025 §scope). Seven to build; thirteen
exist in some form and are verified against their full §3b variant axes,
completing any missing axis:**

To build (7): **Bulk action bar** (hidden · visible) · **Row action menu**
(closed · open · item-hover · item-danger) · **Filter chip** (default ·
hover · removable · active) · **Search field** (empty · typing · with-clear ·
no-results) · **Modal** (`Kind=` confirm · confirm-danger · form · wide ×
`State=` default · submitting) · **Tooltip** (top · bottom · left · right) ·
**Line chart** (1 series · 2 series × `State=` live · static · no-data).

Exist — verify each against its full §3b axis list, complete what is missing
(13): **Table header cell** (`Sort=` none · asc · desc × `State=` default ·
hover) · **Table row** (satisfied by the six per-table row components per
COMPONENTS §2 — verify they still cover their screens; no generic row is
recreated) · **Table row skeleton** (`Skeleton` `Shape=Row`) · **Checkbox**
(unchecked · checked · indeterminate · disabled × focus) · **Pagination**
(default · first-page · last-page · single-page) · **Skeleton** (row · card ·
chart · pane · text-line, one component) · **Spinner** (sm · md × `Context=`
on-surface · on-brand) · **Empty state** (`Kind=` first-run · filtered ·
no-results, each icon + title + body + action) · **Error state** (`Kind=` fetch
· permission · timeout · partial, each with retry) · **Toast** (info · success
· warning · danger × with-action · dismissible) · **Select** (closed · open ·
disabled · error × with-value · placeholder) · **Toggle** (off · on · disabled
× focus) · **Stat strip counter** (= `Metric tile`; the unavailable variant is
the partial-counter state).

The second early/required item, from BUILD_PLAN 3.9 inline: **a size-tolerant
`Skeleton`** — `Shape=Card` overflows when resized, which collides with §1's
requirement that a skeleton hold the height it replaces. `Skeleton` is one of
the thirteen existing sets above; its fix is done first inside Half A, with
the `Metric tile` completion, because those two are what later work trips
over.

**Half A constraints (COMPONENTS.md §4 — each cost a visual regression):**

1. An instance's children cannot be moved and auto-layout widths do not
   persist as overrides. Data-driven geometry is a fill override or a resized
   instance in a frame — never a child move.
2. `createInstance()` drops paint-level opacity on variable-bound fills —
   re-check opacity after instancing anything translucent (the overlays).
3. A duplicate property name is silently renamed (`Detail` → `Detail2`).
4. **Capture a baseline of existing overrides before adding any property**
   (adding one reset 5 of 300) and spot-check against it afterwards.
5. Text properties only where a developer will read the component's API. An
   instance overrides its own text; a property is an API surface, not a
   precondition. `Selector field` carries 68 strings with none.
6. Every screen frame stays a composition of instances (ADR-0032). A
   hand-drawn element that duplicates a component is a review finding.

### Half B — the React components (`frontend/src/components/`)

One file per component, props in / markup out, **no fetching** (spec 006 §1),
no `forwardRef` (React 19), semantic token utilities only (`text-state-broken`,
`bg-surface` — raw palette classes fail the build by design, ADR-0018).
Each file carries a one-line header comment naming its Figma component (the
`COMPONENTS.md` §1 name) — five names differ between §3 and the file, and the
catalog is the cross-reference.

**The code-side mapping of the same ADR-0025 scope — 31 components:**

From §3a (14): `Button` · `Input` · `Card` · `Tag` · `ProgressBar` · `Tabs` ·
`StatePill` (Figma `State pill`; DESIGN_SYSTEM `<DomainStatePill>`) ·
`MetricTile` (also serves Stat strip counter; renders a `null` counter as the
unavailable tile — ADR-0025's consequence on `/overview`) · `Banner` ·
`SelectorField` · `Confidence` · `ValidationBadge` · `SampleCell` ·
`Sparkline`.
_Excluded:_ Sidebar/Topbar (their React code is 3.8's `AppShell`; Half A
still completes their Figma variants) and the Logo set (export asset, no
component).

From §3b (17): `TableHeaderCell` · `RowActionMenu` · `FilterChip` ·
`SearchField` · `BulkActionBar` · `Checkbox` · `Pagination` · `Select` ·
`Toggle` · `Skeleton` · `Spinner` · `EmptyState` · `ErrorState` · `Toast` ·
`Modal` · `Tooltip` · `LineChart`.
_The "Table row" set has no shared React component:_ Figma's generic `Table
row` was deleted (hard-wired to one column set) and the six concrete rows are
screen work — `Domain row` lands with 3.10, the others with their screens.
Its shared deliverable here is the row skeleton (`Skeleton shape="row"`,
asserted below) over the existing `--sp-row-comfortable` / `--sp-row-compact`
spacing tokens.

If `EmptyState`/`Toast` need an icon mechanism, Figma's `Icon` (13 glyphs)
may be coded as a dependency — record it in `COMPONENTS.md`; do not invent
unlisted components beyond that.

**Documentation is a first-class deliverable (the human asked for it):**

- `docs/COMPONENTS.md` re-measured to the **final** state after Half A:
  component and variant counts, §1 used-by table, §5 closed out (§3a 17/17,
  the §3b unbuilt list reduced to the fourteen screen-deferred sets), the
  override-reset incidents recorded if any.
- `docs/DESIGN_SYSTEM.md` gains an entry for every new coded component,
  with the mockup-class cross-reference where one exists (many §3b sets have
  none — the Figma component is then the reference).
- The per-file catalog header comment (above) is the code-side convention.

## Decided (planner)

- **Sequencing: Figma first, then code, then docs.** Half A changes variant
  axes, names and the Skeleton's sizing behaviour — coding against the
  current library would encode the very disagreements Half A fixes and get
  rewritten. The code half builds against the final library state;
  `COMPONENTS.md` is re-measured between the halves so Half B has ground
  truth; `DESIGN_SYSTEM.md` entries land with the code.
- **No ADR.** ADR-0025 §scope carries both lists and the dividing line,
  ADR-0031 the artifact axes, ADR-0032 the composition rule and property
  discipline, ADR-0018 the token/palette enforcement. The reorder is
  sanctioned by BUILD_PLAN's own preamble (recorded above). The code-side
  mapping (Sidebar/Topbar React → 3.8; no generic Table row) is the ADR-0025
  lists applied, not a new structural decision.
- **Test harness: prefer zero new devDependencies.** `react-dom`'s
  `renderToStaticMarkup` renders each variant to a string in vitest's default
  node environment — variant coverage needs no DOM harness and no install. A
  jsdom/happy-dom + testing-library harness is permitted only if genuinely
  required (interaction states a string render cannot express); it adds dev
  deps installed in-container (never on the host, AGENTS rule 1) and is
  recorded in the handoff log. Dev deps need no ADR; runtime deps would.
- **Tokens are not owned.** `design/tokens/*` is shared with the mockups and
  the Figma variables; every token §3 asks for has landed (phase 0). A
  genuinely missing semantic utility is a stop-and-say, not an in-slice edit.
- The two early items (Metric tile unavailable, size-tolerant Skeleton) are
  done first inside Half A — the frames contradiction and the §1
  hold-the-height requirement are the two things later work trips over.

## Files this slice owns

- Figma file `GeJPFXY4CicHBdzLMyXG2E`, page 🧩 Components `3:138` — all
  component work. Page 🖥 Screens `3:139` **only** to reconcile the five
  Partial frames' `Metric tile` instances to the new `State=unavailable`
  variant; no other screen-frame edits.
- `frontend/src/components/**` (new; `ThemeToggle.tsx` untouched)
- `frontend/tests/**` (new test files under `frontend/tests/`;
  `frontend/vite.config.ts` only if a DOM test environment is added)
- `frontend/src/styles/**` (only if a missing semantic utility genuinely
  blocks a component — see Decided; expected: untouched)
- `docs/COMPONENTS.md`, `docs/DESIGN_SYSTEM.md`
- `.tasks/feat-3.9-design-system-components.md` (this file)

**Not owned:** `docs/UI_STATES.md` (the authority — unchanged),
`docs/specs/006-frontend.md`, `docs/BUILD_PLAN.md` (no tick), `design/**`,
`frontend/src/App.tsx`, `frontend/src/hooks|lib|api/**`, backend/BFF trees.

## Acceptance

_(Written so the test role can work from this file plus `UI_STATES.md` §3
without the implementation conversation. Every shipped variant set gets a
test that fails without it.)_

Half A — Figma:

- [x] All eleven §3a completions in the table above exist on 🧩 Components,
      each validated against `UI_STATES.md` §3a; Confidence and Validation
      badge verified complete; Button · Card · State pill · Logo set verified
      still complete.
- [x] `Metric tile State=unavailable` demonstrably exists **and** the five
      Partial frames agree with it (no em-dash override fighting a component
      that has no such variant). _(Measured: only two of the five frames
      carried the override; both reconciled — see handoff log.)_
- [x] `Skeleton` is size-tolerant: `Shape=Card` resized does not overflow —
      it holds the height it replaces (§1).
- [x] The seven unbuilt §3b sets exist with their full variant axes (listed
      in Half A); the thirteen existing sets verified axis-by-axis against
      §3b, missing axes completed.
- [x] §4 constraints held: no instance child moved/resized; paint opacity
      re-checked after any `createInstance` on variable-bound fills; no
      duplicate property names; override baseline captured **before** any
      property addition and re-checked after. _(Two new constraints found and
      recorded — COMPONENTS.md §4 items 4–5.)_
- [x] Inventoried through `figma.root.children` via `use_figma`, never a bare
      `get_metadata`.

Half B — code:

- [ ] 31 component files, one per file, props in / markup out, no fetching,
      no `forwardRef`, header comment naming the Figma component.
- [ ] Every shipped variant set is covered by a Vitest test that fails
      without it — each variant renders distinguishing markup.
- [ ] **The mandated assertion:** `Skeleton shape="row"`'s height is
      `--sp-row-comfortable`, resolved against `design/tokens/tokens.css`
      (36 px) — a hardcoded height fails the test. (BUILD_PLAN 3.9,
      UI_STATES §6.)
- [ ] `MetricTile` renders a `null` counter as the unavailable state (the
      partial-counter contract, ADR-0025).
- [ ] No raw palette class anywhere in the new files (the existing
      `palette-guard` test scans `src/` — it must stay green) and both themes
      hold: components consume semantic utilities so `data-theme="dark"`
      needs no per-component branch; at least one test renders representative
      components under `data-theme="dark"`.
- [ ] `tsc --noEmit` clean (strict, `noUncheckedIndexedAccess`); eslint +
      prettier clean; `make check` green.

Docs:

- [ ] `COMPONENTS.md` reflects the final measured state (counts, §1 used-by,
      §5 closed out) and records any override-reset incident.
- [ ] `DESIGN_SYSTEM.md` carries an entry for every new coded component.
- [ ] No BUILD_PLAN tick (the human ticks in the PR).

## Handoff log

- **Half A — Figma library (2026-10-24, session `04e77cfb`, this pass).**
  Everything in the Half A acceptance list is done; live in file
  `GeJPFXY4CicHBdzLMyXG2E`, page 🧩 Components. Node ids: Metric tile
  `11:71` · Input `42:156` · Tag `43:146` · Progress bar `43:270` · Tab
  `10:100` · Banner `11:84` · Selector field `11:142` · Sample cell `10:83` ·
  Sparkline `10:93` · Skeleton `33:120` · Nav item `84:195` · Sidebar
  `84:8306` · Topbar set `196:1280` · Toast `34:201` · Select `51:293` ·
  Toggle `51:303` · Pagination set `196:1332` · Bulk action bar `199:1294` ·
  Row action menu `199:1306` · Filter chip `199:1316` · Search field
  `199:1339` · Modal `201:1381` · Tooltip `201:1406` · Line chart `201:1489`.
  Library now 56 components · 352 variants; Screens page unchanged at 62
  frames · 1,761 instances — no instance count moved.
  - **Overrides reset: zero, measured.** Baselines captured before mutation
    for the four property-risk groups (93 Input, 62 Topbar, 2 Pagination, 48
    Metric tile instances; deterministic name+type+text hashes) and re-run
    after the changes: 0/205 changed. One real reset was **caught and fixed
    inside the pass**: the page-clone path drops `componentPropertyReferences`,
    so the first swap of the Partial tiles to `State=Unavailable` lost their
    Label overrides; re-wiring all six new Metric tile variants and
    re-applying the two labels restored them (verified by text dump). Recorded
    as §4 constraint 4 in `COMPONENTS.md`.
  - **Early item 1 (Metric tile unavailable):** variant exists (3 tones ×
    loaded/loading/unavailable); reconciled instances `98:9162` (Domains
    Partial, Tone=Default) and `85:8582` (Schedules Partial, Tone=Attention).
    **Conflict found, per instructions:** the contract says five Partial
    frames override a Value to an em dash — only **two** do (Run monitor and
    Reports Partials show all-live counters; Runs history Partial has no
    counter strip). The two that exist are reconciled; the other three frames
    needed nothing.
  - **Early item 2 (size-tolerant Skeleton):** Card/Chart/Pane converted to
    absolute children with SCALE constraints; `Shape=Card` instance resized to
    190×96 holds all four bars inside bounds (numeric bounds check — this
    agent cannot read images; the proof is the child-bounds dump in the
    session, and `skeleton.png` among the evidence). `Shape=Row` = 36 px =
    `--sp-row-comfortable`.
  - **Design calls recorded** (all in COMPONENTS.md §5 too): Tag keeps `Tone`
    (feedback semantics, like Banner/Toast); Input prefix/clear are BOOLEAN
    properties, not variants (pure show/hide); §3a `State=pending` drawn as
    `Result=Pending` / `Trend=Pending`; collapsed sidebar is a dot rail (Nav
    item has no icons — it gained `Collapsed=No·Yes`); Modal is the dialog
    card only, no scrim (no token-legal scrim colour exists — flag to the
    human if a scrim token is wanted); Line chart series bind `viz/1`/`viz/2`.
  - **Deliberate changes to existing instances (recorded, not silent):** the
    two Schedules Pagination instances inherit First-page's ghosted prev
    chevron and the root fill moving from hardcoded white to `bg/base` — both
    are the state §3b specifies for first-page, and the fill is visually
    identical on the page background. Input instances gained two hidden
    prefix/clear children (invisible while the properties are false).
  - **Screenshot evidence** (one per changed set, 24 PNGs) in
    `/private/var/folders/4p/g8xnt_6168l0bqf8ylbj4jnc0000gp/T/opencode/figma-3.9-halfA/`:
    metric-tile · input · tag · progress-bar · tab · banner · selector-field ·
    sample-cell · sparkline · skeleton · nav-item · sidebar · topbar · toast ·
    select · toggle · pagination · bulk-action-bar · row-action-menu ·
    filter-chip · search-field · modal · tooltip · line-chart (`.png`). A
    vision-capable review of these is the one check this pass could not do
    itself.
  - **§4 constraint-2 note:** nothing translucent was instanced into a
    component this pass (Modal has no scrim; Line chart's pulse ring uses
    node-level opacity inside the component, not paint-level opacity on an
    instanced fill), so the `createInstance()` opacity drop had no surface to
    bite — re-check when screens first instance Modal/Line chart.
  - Six stray unnamed COMPONENT nodes (debris from a failed Row-action-menu
    build attempt) were deleted; the page is 56 clean children.
- planner — contract above. Read ADR-0025 §scope (both lists are copied
  there, not re-derived), `COMPONENTS.md` §4–5, `UI_STATES.md` §1–3,
  `DESIGN_SYSTEM.md`, spec 006 §1–3. Figma access verified this session;
  implementer uses the Figma MCP with the `/figma-use` and
  `/figma-generate-library` skills for component creation. Sequencing:
  Figma → re-measure → code → docs (Decided). Frontend tree verified:
  `components/` holds only `ThemeToggle.tsx`; tests live in
  `frontend/tests/`; `--sp-row-comfortable: 36px` is in `tokens.css` and
  mapped in `tailwind-theme.css`; theme is `data-theme="dark"` on `<html>`.

## Open questions

- **§5's "17 still unbuilt" heading counts 16 rows** — **resolved by the Half
  A re-measure: 16 was right.** 34 §3b sets − 20 in ADR-0025's shared scope −
  14 screen-deferred sets covering 9 further components = 16 unbuilt before
  this slice; after Half A, exactly those 9 remain (COMPONENTS.md §5). The
  "17" and BUILD_PLAN's "seventeen" were both wrong; a docs pass can correct
  BUILD_PLAN's mention.
- **Tag's `Tone=` axis** — **resolved: Tone stays.** The one rule says colour
  carries state, and Tag's tones map to feedback semantics exactly as Banner's
  and Toast's tones do (success=verified, warning=stale, danger=broken);
  removable/disabled arrived as orthogonal `Removable`/`Disabled` axes
  (20 variants). Recorded in COMPONENTS.md §5.
- **Spec 006 §2's counts are stale** ("39 components against §3's 51" —
  `COMPONENTS.md` measures 49). Not this slice's file; flagged for a docs
  pass rather than edited here.
- `design/mockups/` gains nothing (populated-state reference only); several
  new components have no mockup class, so their `DESIGN_SYSTEM` entries cite
  the Figma component instead.
