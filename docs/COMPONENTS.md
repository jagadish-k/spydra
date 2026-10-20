# Spydra — component catalog

**What exists in Figma, what each is used by, and what `UI_STATES.md` §3 still
asks for.** Read from the Figma file, not from the specs — so where this file
and a spec disagree, this file describes reality and the spec describes intent.

Figma file [`GeJPFXY4CicHBdzLMyXG2E`](https://www.figma.com/design/GeJPFXY4CicHBdzLMyXG2E/Spydra),
page `🧩 Components` (`3:138`). Screens are page `🖥 Screens` (`3:139`); the
registry is [`SCREENS.md`](SCREENS.md).

**49 components, 230 variants, instanced 1,761 times across 62 frames.**
41 are used by a screen; 8 are not, and §2 says why each.

> **Cardinal rule (ADR-0032): anything above a primitive is a component here,
> and a screen frame is a composition of instances.** Primitives are layout
> containers, text nodes and page scaffolding — that list is closed. A
> hand-drawn element that duplicates a component is a review finding.

---

## 1. Reuse, measured

| Component          | Instances | Screens |
| ------------------ | --------: | ------: |
| Nav item           |       620 |      12 |
| Button             |       144 |      12 |
| Sample cell        |       120 |       3 |
| Input              |        93 |      12 |
| Table header cell  |        70 |       7 |
| State pill         |        64 |       8 |
| App shell/Sidebar  |        62 |      12 |
| App shell/Topbar   |        62 |      12 |
| Logo/Mark adaptive |        62 |      12 |
| Skeleton           |        59 |      10 |
| Metric tile        |        48 |       4 |
| Selector field     |        36 |       3 |
| Log line           |        42 |       1 |
| Tag                |        32 |       4 |
| Confidence         |        26 |       3 |
| Empty state        |        17 |      12 |
| Error state        |        12 |      12 |
| Domain row         |        21 |       1 |
| Domain card        |        12 |       1 |
| Chat message       |        12 |       1 |
| Banner             |        11 |       7 |
| Schedule row       |        10 |       1 |
| Field highlight    |        10 |       1 |
| …plus 18 more      |           |         |

**Ten of 49 carry TEXT properties, and that is a deliberate ceiling.**
A Figma instance can override its text without any component property — the
file proves it: `Selector field` carries 68 distinct strings across its
instances and has no text property at all. Properties buy a named,
discoverable API and overrides that survive a variant swap; they are not a
precondition for anything, and each one risks resetting existing overrides
(ADR-0032). Add them where a developer will read the component's API —
`Button`, `Input`, the row components — not everywhere.

## 2. The eight not used by a screen

| Component                                               | Why                                                                                                                                                                               |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Logo/Mark` · `Logo/Favicon` · `Logo/Lockup horizontal` | Export assets and the Cover. Not app chrome.                                                                                                                                      |
| `Card` · `Kbd` · `Toast` · `Toggle`                     | **Specified in `UI_STATES.md` §3b, drawn by no screen yet.** Not violations — there is nothing hand-drawn for them to duplicate. They land with the screen that first needs them. |
| `Screenshot viewport`                                   | A 420×300 library specimen of the overlay mechanic. Screens draw their own full-size panes; it documents the pattern rather than being instanced.                                 |

**`Table row` was deleted.** It was hard-wired to the Domains column set, so
it fitted one of the app's six tables and nothing instanced it. `UI_STATES.md`
§3b's "Table row" row is now satisfied by six per-table row components — a
different column set is a different component (ADR-0032).

## 3. What the remediation closed

Every table in the app hand-drew its own rows and header cells. Six row
components now carry them, each reused across every frame of its screen:

| Component              | Screen          | Variants                        |
| ---------------------- | --------------- | ------------------------------- |
| `Domain row`           | 1 Domains       | `State=` Default·Hover·Selected |
| `Template version row` | 2 Domain detail | `Active=` Current·Superseded    |
| `Seed row`             | 3 Seeds         | `Resolved=` Yes·No              |
| `Unknown page row`     | 5 Unknown pages | `Actions=` Two·One              |
| `Run row`              | 7 Runs history  | `Live=` Yes·No                  |
| `Product row`          | 8 Products      | `PriceChange=` Yes·No           |
| `Schedule row`         | 11 Schedules    | `State=` Default·Hover·Selected |

Each variant axis is the shape the screen actually varies, found by reading
the drawn rows — not an invented taxonomy. Alongside them:

- **`Log line`**, **`Domain card`** and **`Chat message`** were rebuilt from
  the drawn elements. The previous components of those names were 758, 330 and
  446 wide against screens drawing 374, 724 and 386 — they had never matched,
  which is why nothing instanced them.
- **`Selection overlay`** (`Mode=` Picked·Proposed·Match·Container) and
  **`Field highlight`** replace the hand-drawn overlay boxes on screens 4 and
  4·S.
- **`Segmented control`** adopted the drawn mode toggle's geometry and is now
  instanced on 4·S.
- `Nav item`, `Pagination`, `Select`, `Checkbox`, `Icon`, `Table header cell`,
  `Metric tile` and `Sparkline` were closed earlier with screen 11.

### Still hand-drawn — four, with reasons

| What                                               | Why it is still a frame                                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Run monitor's run-progress summary card (1,160 px) | One per screen, no second caller. A component would have one instance; worth making when a second run view appears.           |
| Template review's `Page preview` pane              | Likewise — one pane, reused across that screen's five frames as part of the frame clone rather than as an instance.           |
| Playground's `Page canvas` pane                    | As above.                                                                                                                     |
| The two `view toggle`s (screens 4 and 8)           | Two segments, not three; `Segmented control` is a three-segment control. Screen 4's is already built from `Button` instances. |

These are **recorded, not hidden**. The first three are one-of-a-kind
containers where a component buys nothing today; the fourth needs a
two-segment control that does not exist yet.

## 4. Three Figma constraints this work established

Worth knowing before the next design pass, because each cost a regression:

1. **An instance's children cannot be moved, and their auto-layout widths do
   not persist as overrides.** Setting `x` on an instance child throws
   `relative-transform cannot be overridden`; resizing an auto-layout child
   silently reverts to the component's value. **Data-driven geometry therefore
   cannot be an override.** The run monitor's per-domain progress bars are
   built as 50 equal ticks whose _fills_ are overridden — fill overrides do
   persist. The instance itself can be freely resized when it sits directly in
   a frame, which is how the row and overlay components carry their sizes.
2. **`createInstance()` drops paint-level opacity on a variable-bound fill.**
   The selection overlays came back opaque at 100% instead of 12% and had to
   have their fills reapplied. Check opacity after instancing anything
   translucent.
3. **Adding a component property whose name already exists silently renames
   it.** `Metric tile` had a TEXT property `Detail`; adding a BOOLEAN `Detail`
   produced `Detail2`. It is now `ShowDetail`.

**And the method that matters:** when replacing a hand-drawn element with an
instance, copy **text, text fills, nested variant properties and nested text**
— all four. Copying only characters lost the Domains sparkline colours and the
Seeds pill labels, both caught only by rendering the frame and comparing
against `design/mockups/`.

## 5. Against `UI_STATES.md` §3

### §3a variant completion — 4 of 17 done

| Component               | §3a asks for                                         | State                                                  |
| ----------------------- | ---------------------------------------------------- | ------------------------------------------------------ |
| Button                  | `State=` default·hover·active·focus·disabled·loading | **done** — 48 variants, plus `Label`                   |
| Card                    | hover · selected · as-skeleton                       | **done** — `State=Loading` is as-skeleton              |
| State pill              | nothing to add                                       | **done**                                               |
| Logo set                | nothing to add                                       | **done**                                               |
| Input                   | focus·error·disabled·readonly·with-prefix·with-clear | partial — no readonly, prefix, clear                   |
| Progress bar            | determinate·stacked·indeterminate·complete·failed    | partial — no **stacked** (screen 6)                    |
| Tag                     | removable · disabled                                 | missing — `Tone=` only                                 |
| Tab                     | hover · disabled · with-count-badge                  | missing                                                |
| Metric tile             | `State=` loaded·loading·**unavailable**              | missing — `Tone=` and `ShowDetail` only                |
| Banner                  | dismissible · with-action                            | missing — `Tone=` only                                 |
| Selector field          | resolving · disabled · **no-match**                  | missing                                                |
| Sample cell · Sparkline | `State=pending`                                      | missing                                                |
| Sidebar · Topbar        | expanded·collapsed · with-breadcrumb                 | **`Active=` and `Breadcrumb` done**; collapsed missing |

**`Metric tile State=unavailable` still has a drawn contradiction**: the five
Partial frames override a `Value` to an em dash instead. **`Skeleton` is still
not size-tolerant** — `Shape=Card` overflows when resized, which collides with
§1's requirement that a skeleton hold the height it replaces. Both are `3.9`.

### Renames between §3 and the file

| `UI_STATES.md` §3b | In Figma                                           |
| ------------------ | -------------------------------------------------- |
| Keycap             | `Kbd`                                              |
| Selection overlay  | `Selection overlay` ✅ (was `Screenshot viewport`) |
| Log line           | `Log line` ✅ (was `Log row`)                      |
| Table row skeleton | `Skeleton` `Shape=Row`                             |
| Stat strip counter | `Metric tile`                                      |
| Table row          | six per-table row components (§3)                  |

### §3b — 17 still unbuilt

| Group                      | Unbuilt                                                        |
| -------------------------- | -------------------------------------------------------------- |
| Tables (1 · 2 · 5 · 7 · 8) | Bulk action bar · Row action menu · Filter chip · Search field |
| States — every screen      | Modal · Tooltip                                                |
| Forms (2 · 3)              | Numeric stepper · Dropzone · Validation row                    |
| Review surfaces (4 · 10)   | Ancestor breadcrumb · Provenance badge · Diff row              |
| Monitoring (6–9)           | Countdown · Line chart · Price history chart · Image thumbnail |

`Dropzone` is the one to notice: screen 3's dropzone has five states in §4 and
is the whole interaction of that screen, and it has no component and no drawn
state beyond the populated frame.

## 6. Screen 11's components

| Component        | Variants                            | Properties                                               |
| ---------------- | ----------------------------------- | -------------------------------------------------------- |
| `Schedule state` | `State=` Enabled · Paused           | —                                                        |
| `Schedule row`   | `State=` Default · Hover · Selected | `Name` `Timezone` `Cron` `Domains` `NextFire` `LastFire` |
| `Fire row`       | `Outcome=` Fired · Skipped · Failed | `When` `Schedule` `Detail`                               |

`Schedule state` is deliberately **not** a seventh `State pill` variant:
`UI_STATES.md` §3a says not to add one without a schema change, and a
schedule's enabled flag is a different lifecycle in a different table
(`ui.schedules.enabled`, spec 011 §1) from a domain's.

## 7. Tokens

| Collection   | Modes        | Variables |
| ------------ | ------------ | --------: |
| `Primitives` | Value        |        55 |
| `Color`      | Light · Dark |        43 |
| `Radius`     | Value        |         6 |
| `Spacing`    | Value        |        10 |
| `Typography` | Value        |        14 |

`Color` is the only collection with a Dark mode, which is correct: spacing,
radius and type do not change with the theme. `DESIGN_SYSTEM.md` is
authoritative for the token names.
