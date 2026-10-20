# Spydra — component catalog

**What exists in Figma, what each is used by, and what `UI_STATES.md` §3 still
asks for.** Read from the Figma file, not from the specs — so where this file
and a spec disagree, this file describes reality and the spec describes intent.

Figma file [`GeJPFXY4CicHBdzLMyXG2E`](https://www.figma.com/design/GeJPFXY4CicHBdzLMyXG2E/Spydra),
page `🧩 Components` (`3:138`). Screens are page `🖥 Screens` (`3:139`); the
registry is [`SCREENS.md`](SCREENS.md).

**42 components — 36 variant sets (217 variants) and 6 singletons — instanced
1,542 times across 62 frames.** `UI_STATES.md` §3 asks for 51 rows; §3 below
reconciles the two, and the difference is not a subtraction.

> **Cardinal rule (ADR-0032): anything above a primitive is a component here,
> and a screen frame is a composition of instances.** Primitives are layout
> containers, text nodes and page scaffolding — that list is closed. A
> hand-drawn element that duplicates a component is a review finding.

---

## 1. Reuse, measured

| Component          | Instances | Screens | Carries content via  |
| ------------------ | --------: | ------: | -------------------- |
| Nav item           |       620 |      12 | `Label` · `Count`    |
| Button             |       144 |      12 | `Label`              |
| Sample cell        |       120 |       3 | — (variant only)     |
| Input              |        93 |      12 | `Text`               |
| State pill         |        64 |       8 | — (variant only)     |
| App shell/Sidebar  |        62 |      12 | `Active=` ×10        |
| Logo/Mark adaptive |        62 |      12 | —                    |
| App shell/Topbar   |        62 |      12 | `Breadcrumb`         |
| Skeleton           |        59 |      10 | — (variant only)     |
| Selector field     |        36 |       3 | — (variant only)     |
| Tag                |        32 |       4 | `Label`              |
| Metric tile        |        30 |       3 | `Label·Value·Detail` |
| Confidence         |        26 |       3 | — (variant only)     |
| Empty state        |        17 |      12 | — (variant only)     |
| Sparkline          |        12 |       1 | — (variant only)     |
| Error state        |        12 |      12 | — (variant only)     |
| Table header cell  |        12 |       1 | `Label`              |
| Banner             |        11 |       7 | — (variant only)     |
| Schedule row       |        10 |       1 | 6 text properties    |
| Checkbox           |        10 |       1 | —                    |
| Schedule state     |        10 |       1 | — (variant only)     |
| Icon               |         8 |       1 | — (variant only)     |
| Fire row           |         8 |       1 | 3 text properties    |
| Tab                |         6 |       2 | — (variant only)     |
| Validation badge   |         5 |       1 | — (variant only)     |
| Select             |         4 |       1 | — (variant only)     |
| Progress bar       |         3 |       1 | — (variant only)     |
| Spinner            |         2 |       2 | — (variant only)     |
| Pagination         |         2 |       1 | `Summary`            |

**Ten of 42 carry text properties.** That number is the one to watch: a
component without one cannot carry its own content, so a screen that needs it
hand-draws the element instead — which is exactly how the sixteen violations
in §2 came about (ADR-0032 §Context). The remaining "variant only" rows are
mostly fine — `State pill` and `Confidence` _are_ their variant — but
`Banner`, `Empty state`, `Error state`, `Selector field` and `Sample cell` all
carry per-screen copy today as raw overrides and should gain text properties.

## 2. Defined but never instanced

Thirteen of the 42 appear in no screen frame.

**Three are not app chrome and never will be** — `Logo/Mark`, `Logo/Favicon`
and `Logo/Lockup horizontal` are export assets and the Cover.

**Ten are ADR-0032 violations**: the screens need them and hand-draw them
instead.

| Component             | The screen region that hand-draws it                       |
| --------------------- | ---------------------------------------------------------- |
| `Table row`           | screens 1 · 5 · 7 · 8 — `7:2` draws `row/…` frames by hand |
| `Card`                | screen 8's card view                                       |
| `Segmented control`   | screen 4's Preview · Select · Skeleton switch              |
| `Screenshot viewport` | screen 4's left pane and the Playground canvas             |
| `Chat message`        | screen 10's transcript                                     |
| `Log row`             | screen 6's log pane                                        |
| `Domain card`         | screen 6's per-domain strip                                |
| `Toast`               | the approve-submitting feedback in `UI_STATES.md` §4       |
| `Toggle`              | the settings rows on screen 2                              |
| `Kbd`                 | the `[` / `]` hints in Select mode                         |

**Six violations were closed on 2026-10-20** by the ADR-0032 work: `Nav item`
(620 instances, from zero), `Pagination`, `Select`, `Checkbox`, `Icon` and
`Table header cell`. The first is the instructive one — the sidebar's nav rows
were hand-drawn frames, and because they were, **the active row was baked in
and all 56 frames showed "Domains" as the current screen.** Four audits missed
it; composing from components made it a question that had to be answered.

**Remediating the remaining ten is not a cosmetic pass.** Each needs its
component to gain text properties first, and **each property addition needs a
baseline of existing instance overrides captured before the change** — adding
six text properties reset 5 of 300 overrides silently (ADR-0032). This is
scoped work that belongs before `3.9`, not a drive-by.

**`Table row` is really `Domain row`.** It is hard-wired to the Domains
table's ten columns, which is why screen 11 has its own `Schedule row`. A
different column set is a different component, not a variant. The rename is
free — it has no instances — and is deferred, not forgotten.

## 3. Against `UI_STATES.md` §3

### The count, reconciled

§3a's heading says **twenty** exist and §3b's footer says **seventeen**. Both
are right and the units differ: seventeen **spec rows**, which collapse the
four logo components into one "Logo set" row and pair Sidebar with Topbar, map
onto **twenty Figma components**.

| Bucket                                      | Spec rows | Figma components |
| ------------------------------------------- | --------: | ---------------: |
| §3a — exist, needing variant completion     |        17 |               20 |
| §3b — exist now, built since §3 was written |        16 |               16 |
| §3b — satisfied by another component        |         1 |                0 |
| §3b — still unbuilt                         |        17 |                0 |
| Not in §3 at all                            |         0 |                6 |
| **Total**                                   |    **51** |           **42** |

The six not in §3 are `Icon`, `Domain card`, `Nav item`, and screen 11's
`Schedule state`, `Schedule row` and `Fire row`. The last three arrived with
their screen and are documented in `SCREENS.md` §11; the first three are
unowned and should be added to §3a or deleted.

### Five components exist under a different name

A name-based audit reports each of these as missing, and three passes did:

| `UI_STATES.md` §3b | In Figma                                   |
| ------------------ | ------------------------------------------ |
| Keycap             | `Kbd`                                      |
| Selection overlay  | `Screenshot viewport` (`Mode=` 4 variants) |
| Log line           | `Log row` (no `Strategy=` axis)            |
| Table row skeleton | `Skeleton` `Shape=Row`                     |
| Stat strip counter | `Metric tile` (no `State=` axis)           |

### §3a variant completion — 4 of 17 done

| Component               | §3a asks for                                         | State                                                        |
| ----------------------- | ---------------------------------------------------- | ------------------------------------------------------------ |
| Button                  | `State=` default·hover·active·focus·disabled·loading | **done** — 48 variants, plus `Label`                         |
| Card                    | hover · selected · as-skeleton                       | **done** — `State=Loading` is as-skeleton                    |
| State pill              | nothing to add                                       | **done**                                                     |
| Logo set                | nothing to add                                       | **done**                                                     |
| Input                   | focus·error·disabled·readonly·with-prefix·with-clear | partial — no readonly, prefix, clear                         |
| Progress bar            | determinate·stacked·indeterminate·complete·failed    | partial — no **stacked** (screen 6)                          |
| Tag                     | removable · disabled                                 | missing — `Tone=` only                                       |
| Tab                     | hover · disabled · with-count-badge                  | missing — selected/default only                              |
| Metric tile             | `State=` loaded·loading·**unavailable**              | missing — `Tone=` only                                       |
| Banner                  | dismissible · with-action                            | missing — `Tone=` only                                       |
| Selector field          | resolving · disabled · **no-match**                  | missing                                                      |
| Sample cell · Sparkline | `State=pending`                                      | missing                                                      |
| Sidebar · Topbar        | expanded·collapsed · with-breadcrumb                 | **`Active=` and `Breadcrumb` done**; collapsed still missing |

**`Metric tile State=unavailable` has a drawn contradiction.** It is the
partial case — numbers with one dash — and the five Partial frames on screens
1 · 6 · 7 · 9 · 11 are already drawn without it, by overriding the `Value`
text to an em dash. The component and the frames disagree until the variant
exists.

**`Skeleton` is not size-tolerant.** `Shape=Card` has absolutely positioned
children, so an instance resized to a metric tile's 190×96 overflows; screen
11's loading frame clips them. `UI_STATES.md` §1 requires a skeleton to hold
the height of the content it replaces, so this is a real `3.9` item.

### §3b — the 17 still unbuilt

| Group                              | Unbuilt                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------- |
| Tables (screens 1 · 2 · 5 · 7 · 8) | Bulk action bar · Row action menu · Filter chip · Search field                        |
| States — every screen              | Modal · Tooltip                                                                       |
| Forms (screens 2 · 3)              | Numeric stepper · Dropzone · Validation row                                           |
| Review surfaces (4 · 10)           | Ancestor breadcrumb · Provenance badge · Diff row                                     |
| Monitoring (6–9)                   | Countdown · Line chart · Price history chart · Image thumbnail · Stat strip counter ᵐ |

ᵐ the `Metric tile` row above; listed twice in §3, counted once here.

`Dropzone` is the one to notice: screen 3's dropzone has five states in §4 and
is the whole interaction of that screen, and it has no component and no drawn
state beyond the populated frame.

## 4. Screen 11's components

Added 2026-10-20 with the Schedules screen, which is ADR-0032's worked example.

| Component        | Variants                            | Properties                                               |
| ---------------- | ----------------------------------- | -------------------------------------------------------- |
| `Schedule state` | `State=` Enabled · Paused           | —                                                        |
| `Schedule row`   | `State=` Default · Hover · Selected | `Name` `Timezone` `Cron` `Domains` `NextFire` `LastFire` |
| `Fire row`       | `Outcome=` Fired · Skipped · Failed | `When` `Schedule` `Detail`                               |

`Schedule state` is deliberately **not** a seventh `State pill` variant.
`UI_STATES.md` §3a says not to add one without a schema change, and a
schedule's enabled flag is a different lifecycle in a different table
(`ui.schedules.enabled`, spec 011 §1) from a domain's.

`Fire row` reuses `Tag` for the outcome rather than inventing a badge, which
is what `Tag`'s `Tone=` axis is for.

## 5. Tokens

Variables are file-level and survive page changes. Five collections:

| Collection   | Modes        | Variables |
| ------------ | ------------ | --------: |
| `Primitives` | Value        |        55 |
| `Color`      | Light · Dark |        43 |
| `Radius`     | Value        |         6 |
| `Spacing`    | Value        |        10 |
| `Typography` | Value        |        14 |

`Color` is the only collection with a Dark mode, which is correct: spacing,
radius and type do not change with the theme. `DESIGN_SYSTEM.md` is
authoritative for the token names; this is only the count, so a missing
collection is visible.
