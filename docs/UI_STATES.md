# UI states — the matrix

Every surface that reads data has more than one state, and a screen designed
only in its populated state is a screen whose loading, empty and error paths
get invented during implementation. This file enumerates them once so the
Figma frames, the React components and the phase 3 acceptance criteria all
read the same list.

Read with [`SCREENS.md`](SCREENS.md) (what each screen is for) and
[`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) (tokens and the one rule).

---

## 1. The four that are never optional

Any component or screen region that renders fetched data has all four:

| State         | When                                       | What it must not do                                                                                                  |
| ------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| **loading**   | the request is in flight                   | collapse the layout — a skeleton holds the same height as the content it replaces, or the page jumps when data lands |
| **empty**     | the request succeeded and returned nothing | look like an error. "No domains yet" and "could not load domains" are different sentences with different actions     |
| **error**     | the request failed                         | strand the user — every error state carries a retry and the reason, not a spinner that never resolves                |
| **populated** | the normal case                            | —                                                                                                                    |

**empty has two sub-cases and they are not interchangeable.** _First-run
empty_ ("you have not added a domain yet") offers the primary action and
explains the concept. _Filtered empty_ ("no domains match `broken` +
`never crawled`") offers to clear the filter and must never offer to create
anything, because the data exists and the filter is hiding it. Screens 1, 5,
7 and 8 need both; the rest need only one.

**Partial is a fifth state on anything that aggregates.** A six-counter strip
where one counter's query timed out shows five numbers and one dash with a
tooltip, not a whole-screen error. Screens 1, 6, 7 and 9.

## 2. Tokens this requires

`DESIGN_SYSTEM.md` forbids a raw hex inside a component, so these live in
`design/tokens/tokens.css` — and are **also** mapped into Tailwind's
`--color-*` namespace in `design/tokens/tailwind-theme.css`, without which
they resolve but generate no utility and `bg-skeleton` silently paints
nothing. Both files or neither.

**Status: landed.** All ten are in `tokens.css` with dark values, and all ten
are mapped in `tailwind-theme.css`. Kept here as the specification of what
they are for.

```css
/* Skeletons — a surface that is deliberately not content */
--sp-skeleton-base: var(--sp-neutral-200);
--sp-skeleton-sheen: var(--sp-neutral-100);

/* Playground overlays. Translucent is mandatory: an opaque overlay hides
   the thing being selected, which is the whole point of the pane. */
--sp-overlay-hover: color-mix(in srgb, var(--sp-brand-500) 12%, transparent);
--sp-overlay-selected: color-mix(in srgb, var(--sp-brand-500) 20%, transparent);
--sp-overlay-match: color-mix(in srgb, var(--sp-fb-warning) 14%, transparent);
--sp-overlay-outline: var(--sp-brand-500);

/* Disabled — a reduction, not a colour of its own */
--sp-disabled-fg: var(--sp-text-muted);
--sp-disabled-bg: var(--sp-bg-subtle);
--sp-disabled-border: var(--sp-border);
```

Dark-mode values follow the same rule as the lifecycle palette: the hue does
not move, only lightness.

**`--sp-overlay-match` is deliberately warning-coloured.** Six matches where
you expected one is the most common selector error, and the overlay that
shows it should read as "look at this", not as a neutral highlight.

## 3. Component variant matrix

### 3a. The twenty that exist, and what they are missing

| Component                                               | Has                   | Must add                                                                                               |
| ------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------ |
| Button                                                  | 4 styles × 2 sizes    | `State=` default · hover · active · focus · disabled · **loading** (spinner, label held, width frozen) |
| Input                                                   | one state             | focus · error · disabled · readonly · with-prefix · with-clear                                         |
| Card                                                    | one state             | hover · selected · **as-skeleton**                                                                     |
| Tag                                                     | one state             | removable · disabled                                                                                   |
| Progress bar                                            | one state             | determinate · **stacked** (run monitor) · indeterminate · complete · failed                            |
| Tab                                                     | selected, default     | hover · disabled · with-count-badge                                                                    |
| State pill                                              | 6 lifecycle           | — (complete; do not add a seventh without a schema change)                                             |
| Metric tile                                             | 3 tones               | `State=` loaded · loading · **unavailable** (the partial case)                                         |
| Banner                                                  | 3 tones               | dismissible · with-action                                                                              |
| Selector field                                          | default/warning/error | resolving · disabled · **no-match** (distinct from error: the selector is valid and matched nothing)   |
| Confidence · Validation badge · Sample cell · Sparkline | complete              | `State=pending` on Sample cell and Sparkline, for before the sample resolves                           |
| Sidebar · Topbar                                        | one state             | Sidebar: expanded · collapsed. Topbar: default · with-breadcrumb                                       |
| Logo set                                                | 4                     | —                                                                                                      |

**`Button/State=loading` freezes its own width.** A button that shrinks to
fit a spinner moves everything beside it, and the one place this matters most
is the approve action on screen 4, where the row beneath jumps under the
cursor mid-click.

### 3b. The components the screens need and the library has none of

Grouped by the screens that force them into existence.

_Tables — screens 1, 2, 5, 7, 8_

| Component          | Variants                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------- |
| Table header cell  | `Sort=` none · asc · desc, × `State=` default · hover                                     |
| Table row          | default · hover · selected · focus-visible · disabled, × `Density=` comfortable · compact |
| Table row skeleton | one, matching `--sp-row-comfortable` exactly                                              |
| Checkbox           | unchecked · checked · indeterminate · disabled, × focus                                   |
| Bulk action bar    | hidden · visible (count + actions)                                                        |
| Pagination         | default · first-page · last-page · single-page                                            |
| Row action menu    | closed · open · item-hover · item-danger                                                  |
| Filter chip        | default · hover · removable · active                                                      |
| Search field       | empty · typing · with-clear · no-results                                                  |

_States and feedback — every screen_

| Component   | Variants                                                                        |
| ----------- | ------------------------------------------------------------------------------- |
| Skeleton    | row · card · chart · pane · text-line (one component, `Shape=` variant)         |
| Spinner     | sm · md, × `Context=` on-surface · on-brand                                     |
| Empty state | `Kind=` first-run · filtered · no-results, each icon + title + body + action    |
| Error state | `Kind=` fetch · permission · timeout · partial, each with retry                 |
| Toast       | info · success · warning · danger, × with-action · dismissible                  |
| Modal       | `Kind=` confirm · confirm-danger · form · wide, × `State=` default · submitting |
| Tooltip     | top · bottom · left · right                                                     |

_Forms — screens 2, 3_

| Component       | Variants                                                     |
| --------------- | ------------------------------------------------------------ |
| Select          | closed · open · disabled · error, × with-value · placeholder |
| Numeric stepper | default · at-min · at-max · error · disabled                 |
| Toggle          | off · on · disabled, × focus                                 |
| Dropzone        | idle · drag-over · parsing · parsed · error                  |
| Validation row  | pass · warn · fail (seeds preview, per row)                  |

_Screen 4 and 10 — the review surfaces_

| Component           | Variants                                                                                                                                 |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Segmented control   | 3 segments × which is active, × disabled-segment. **Not the Tab component** — Tab navigates, this switches a rendering of the same thing |
| Selection overlay   | hover · selected · match · multi-match-warning                                                                                           |
| Keycap              | single · pair (`[` `]`)                                                                                                                  |
| Ancestor breadcrumb | 2–6 levels, with the current level marked                                                                                                |
| Chat message        | `From=` user · system, × `Kind=` statement · refusal · error · streaming                                                                 |
| Provenance badge    | form · chat · clicked                                                                                                                    |
| Diff row            | unchanged · added · removed · changed                                                                                                    |

_Screens 6–9 — monitoring and reporting_

| Component           | Variants                                                                      |
| ------------------- | ----------------------------------------------------------------------------- |
| Log line            | `Status=` ok · warn · error, × `Strategy=` structured · selector · llm · none |
| Countdown           | counting · eligible-now · paused                                              |
| Line chart          | 1 series · 2 series, × `State=` live · static · no-data                       |
| Price history chart | with-change · flat · single-point · no-data                                   |
| Image thumbnail     | default · deduped · missing · broken                                          |
| Stat strip counter  | value · zero · unavailable · active-filter                                    |

That is **51 component sets**, of which 17 exist in some form and 34 do not.
A row naming several components separated by `·` counts as one set each; the
§3a rows collapse related ones to keep the table short, which is where an
earlier count of 45 came from.

`3.9` builds the **shared** sets — the §3a variant completions plus the §3b
sets used by three or more screens. The other fourteen arrive with the screen
that needs them, still before it renders, so the ordering rule that components
precede screens holds per screen rather than across the phase. ADR-0025
§scope carries both lists; read it rather than re-deriving them from the
screen counts above.

## 4. Per-screen states

Beyond the four from §1, each screen has states that are specific to what it
does. These are the ones that get missed.

| Screen                | Additional states                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **1 Domains**         | filtered-empty · partial-counters (one counter failed) · bulk-selection-active · sorting · all-paused                                                                                                                                                                                                                                                                                                                                                        |
| **2 Domain detail**   | per-tab loading · `robots.txt` unavailable · `Crawl-delay` overriding your value · template diff with no differences · domain auto-paused (banner)                                                                                                                                                                                                                                                                                                           |
| **3 Seeds**           | dropzone idle/drag-over/parsing/error · preview with all-valid · preview with some-invalid · preview with **all** invalid (confirm disabled) · CSV template downloading                                                                                                                                                                                                                                                                                      |
| **4 Template review** | **three modes** (Preview · Select · Skeleton — Preview is phase 3; Select and Skeleton render as disabled segments until `4.10` and `6.10`) × loading screenshot · screenshot unavailable · field resolving · field no-match · field multi-match (the warning overlay) · sample strip partially resolved · sample strip with a failing column · dry-run discovery empty/huge · batch grid loading/mixed/all-approved · approve submitting · approve rejected |
| **5 Unknown pages**   | grouped-empty · group expanded with snapshot · **snapshot expired past its 7-day TTL** · dismiss-as-deny-pattern confirm                                                                                                                                                                                                                                                                                                                                     |
| **6 Run monitor**     | connecting · live · **SSE reconnecting** (backfilling, not frozen) · reconnect failed · run paused · run stopping · a domain auto-paused and sorted to top · asset queue backpressure · log pane paused · run complete                                                                                                                                                                                                                                       |
| **7 Runs history**    | no runs yet · run detail expanded · comparison with two selected · comparison with nothing materially changed                                                                                                                                                                                                                                                                                                                                                |
| **8 Products**        | table view · card view · no images · product detail with one observation (no history to chart) · price history with a template-version change marked                                                                                                                                                                                                                                                                                                         |
| **9 Reports**         | each report loading · report with no rows in range · export generating · export failed                                                                                                                                                                                                                                                                                                                                                                       |
| **10 Authoring chat** | idle (no URLs yet) · fetching · streaming reply · **refusal** (over the 5-page limit, another domain, asking for a run) · draft partially verified · draft complete · open-in-review handoff                                                                                                                                                                                                                                                                 |

**Screen 6's reconnecting state is the one to get right.** The browser will
sleep, SSE will drop, and the difference between "reconnecting, backfilling
from event 1,284" and a frozen progress bar is the difference between a user
who waits and a user who restarts a crawl that was fine.

Both themes for every frame is not required. Build **light for all**, and
**dark for one screen per visual pattern** — table (1), three-pane (4),
live-updating (6), chat (10) — which is enough to catch a token that was
never given a dark value without quadrupling the frame count.

## 5. Prototype

One flow, starting on screen 1, demonstrating transitions rather than only
navigation.

```
Domains (loading) ──after 800ms──→ Domains (populated)
  │ click a row              → Domain detail · Templates tab
  │ click a counter          → Domains (filtered) ──→ filtered-empty
  │ click "Review" on a row  → Template review (loading)
                                 └─after 600ms→ Template review (Preview)
                                      │ segmented control → Select → Skeleton
                                      │ click a field     → multi-match warning
                                      │ Approve           → submitting → toast → back to Domains
  │ sidebar → Seeds          → dropzone idle ──drag──→ parsing ──→ preview
  │ sidebar → Run monitor    → connecting ──→ live ──→ reconnecting ──→ live
  │ sidebar → Unknown pages  → grouped ──expand──→ snapshot
```

Smart Animate on the three-pane mode switch and on overlay appearance;
instant on navigation. After-delay triggers carry the loading→populated
transitions, because a loading state nobody can reach is a frame nobody
checks.

## 6. What this means for the build plan

The React components in phase 3 are built against this matrix, not against a
populated screenshot. This is binding, not advisory (ADR-0025). Concretely:

- A component PR that adds only the populated path is incomplete, and the
  reviewer (`spydra-reviewer`) reads this file to know what is missing — its
  role file says so, and BUILD_PLAN §3b carries it in the definition of done.
- `Skeleton` heights are asserted against `--sp-row-comfortable` in a test
  (BUILD_PLAN `3.9`), because a skeleton that is the wrong height is a layout
  jump that no screenshot review catches.
- The SSE reconnect path (screen 6) gets a test that drops the connection and
  asserts backfill from `Last-Event-ID`. Server-side backfill is `3.6`; this
  client-side test is **`3.16` acceptance**, not a phase 5 hardening task.
- Screen 1's partial-counter state requires every counter in
  `/api/ui/overview` to be nullable (spec 011 §5). A flat `number` cannot
  express one counter that did not resolve.

**§4 spans more than phase 3.** Screens 5, 9 and 10 arrive in `4.8`, `5.8`
and `4.12`; the instruction above is scoped to the screens the phase actually
builds, so a reviewer does not file findings against unbuilt surfaces.
