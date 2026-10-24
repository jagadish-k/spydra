# chore/3.9-storybook

**Task:** human-directed chore under 3.9's umbrella — Storybook for the
design-system components. **There is no BUILD_PLAN task to tick** (the human
ticks BUILD_PLAN entries in PRs; this one has no entry by design — noted
here so nobody goes hunting). Not stacked into 3.9's PR; a sibling branch on
top of its tip.
**Stacked on:** `feat/3.9-design-system-components` (`575c62f`, PR pending) —
the 31 components this slice documents are that branch's Half B.
**Spec:** none governs tooling; nearest kin is `docs/specs/006-frontend.md` §1
(props in / markup out) · **Matrix:** `docs/UI_STATES.md` §3 ·
**Reference:** `docs/DESIGN_SYSTEM.md` §"The coded library" (the prop-axe
table) · `frontend/tests/components-{3a,3b}.test.tsx` (the per-arm
enumeration the stories mirror)
**ADRs:** 0017 (latest stable, verified on the registry), 0010/AGENTS rule 1
(Docker-native — nothing installs on the host), 0018 (tokens; the
palette-guard test scans `src/`), 0031 (UI spec artifacts — **Storybook must
not become a fourth**). New: **ADR-0043** (below).

## Verified facts — do not re-research (checked 2026-10-24)

Registry, in the `web` container (`docker compose run --rm --no-deps web npm
view …`); docs via ctx7 (`/storybookjs/storybook`, `/chromaui/chromatic-docs`).

- **`storybook` latest = 10.6.3** (dist-tag `latest`; v10 minor is **10.6**).
  Package layout v10: the **unified `storybook` package** + one framework
  package, **`@storybook/react-vite` 10.6.3**. No `@storybook/react`,
  no `@storybook/addon-*` core packs needed.
- **`@chromatic-com/storybook` 5.6.0** — peer range includes `^10.6.0-0` ✓.
  Installed as the lone addon entry: `"@chromatic-com/storybook"` (object
  form with `options` only if needed). Docs: visual-tests-addon.mdx.
- **`chromatic` CLI 18.13.3** — dev dep; CI publishes a prebuilt storybook
  with `--storybook-build-dir` (configuration/cli.mdx).
- **Storysource is dead on v10 — its successor is the built-in Code Panel.**
  `@storybook/addon-storysource` latest is **8.6.14**, peers `^8.6.14`; the
  v9 MIGRATION.md is explicit: "The `@storybook/addon-storysource` addon and
  the `@storybook/source-loader` package are removed in Storybook 9.0…
  Storybook now provides a Code Panel via `@storybook/addon-docs`". In v10
  docs it is core: enable globally with
  `parameters: { docs: { codePanel: true } }` in `preview` (docs:
  `writing-docs/code-panel.mdx`). **"Storysource working" = Code Panel on**;
  installing the 8.x addon against storybook 10 is a defect.
- **Manager theme: do nothing.** SB's default `themes.normal` follows the OS
  light/dark, which _is_ "match the app's two themes". No `manager.ts`
  (docs: `configure/user-interface/theming.mdx`).
- **`storybook init` is not run.** It is interactive and host-minded; here it
  would be a worse version of what this slice does by hand: `npm install -D`
  in the `web` container + a hand-written `.storybook/`.

## Contract

### Package + scripts (`frontend/package.json`, lockfile via in-container install)

devDependencies (ADR-0017 style, caret majors):
`storybook ^10.6.3` · `@storybook/react-vite ^10.6.3` ·
`@chromatic-com/storybook ^5.6.0` · `chromatic ^18.13.3`.

scripts:
`"storybook": "storybook dev -p 6006 -h 0.0.0.0 --no-open"` (host flag — the
port must be reachable through the container boundary; `--no-open` — nothing
to open in a container) ·
`"build-storybook": "storybook build"` (default output `storybook-static/`).

Install: `docker compose run --rm --no-deps web npm install -D …` — updates
the `web_modules` volume and the lockfile on the bind mount. CI's fresh image
build (`npm ci`) picks the deps up from the lockfile; nothing else to do.

### `.storybook/` (new, at `frontend/.storybook/`)

- **`main.ts`** — `framework: "@storybook/react-vite"`,
  `stories: ["../src/**/*.stories.tsx"]`,
  `addons: ["@chromatic-com/storybook"]`. SB reads `vite.config.ts` itself,
  which brings the Tailwind v4 plugin and the `fs.allow` for `/design` — do
  not duplicate vite config here.
- **`preview.tsx`** — three things:
  1. `import "../src/styles/theme.css"` (the app's single style entry; the
     relative `../../../design/tokens/*` imports resolve to the read-only
     `/design` mount the `web` service already carries).
  2. `parameters.docs.codePanel: true` — the Storysource successor.
  3. **The theme decorator + toolbar** (see next section).
- No `manager.ts`.

### Both themes — the call: toolbar global, not pairwise stories

The dark tokens are scoped **`:root[data-theme="dark"]`**
(`design/tokens/tokens.css:219`); a wrapper `<div data-theme>` does nothing,
and light is the attribute's absence (`frontend/index.html` sets it on
`documentElement` only when dark). So the decorator sets the attribute on
the **canvas iframe's `documentElement`**:

```tsx
// preview.tsx sketch — theme global -> <html data-theme> of the story iframe
const preview: Preview = {
  globalTypes: {
    theme: {
      toolbar: { title: "Theme", items: ["light", "dark"], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "light" },
  decorators: [
    (Story, context) => {
      const theme = context.globals.theme;
      // :root[data-theme="dark"] — must land on documentElement, not a wrapper
      document.documentElement.setAttribute(
        "data-theme",
        theme === "dark" ? "dark" : "light",
      );
      return <Story />;
    },
  ],
  parameters: { docs: { codePanel: true } },
};
```

(A `useEffect`-based variant is fine if render-time mutation trips React 19
strict-mode warnings — the attribute set is idempotent either way. Setting it
for light too — rather than removing it — matches nothing in prod but is
harmless and simpler; `:root[data-theme="light"]` has no block.) Docs pages
also render in an iframe, so the same decorator covers them.

**Chromatic captures stories in the default (light) global.** Dark-theme
Chromatic coverage would need duplicated stories or `--args` capture —
explicitly out of scope (below); the toolbar is for the human's eyes.

### Stories — 31 files, colocated, one story per axis value

`frontend/src/components/<Component>.stories.tsx`, one per 3.9 component
(`ThemeToggle` excluded — app chrome, not the library). CSF3,
`satisfies Meta<typeof Component>`, strict-TS clean.

**Granularity (pinned):** every **persistent prop axis value** from
DESIGN_SYSTEM §"The coded library" gets a named story — Chromatic's one-story-
per-variant-state requirement, satisfied for free later. Where the existing
matrix tests exercise a state only as a combination (e.g. Modal
`Kind=confirm-danger × State=submitting`, LineChart 2-series × live), that
combination is a story too. Mirror `frontend/tests/components-{3a,3b}` — it
is the arm enumeration; do not invent combinations it does not test.

**No hover/focus/pressed stories.** Those arms are `hover:`/`focus-visible:`/
`active:` utilities in the markup (3.9's Figma-arm→React mapping), not props;
a story named "Hover" cannot hover. The classes are visible in the Code
Panel and asserted by the vitest matrix. Faking them with Chromatic
interactions is out of scope.

Stories use no colour classes at all in their own wrappers (the palette-guard
test scans `src/`); layout-only or no classes.

### Makefile + CI

- `make storybook` — `docker compose run --rm --no-deps -p 127.0.0.1:6006:6006
web npm run storybook`. `run -p`, not a compose port and not
  `--service-ports` (those would fight the dev container's 5173 or pin a
  port only used on demand). Loopback-only, like every published port.
- `make storybook-build` — `docker compose run --rm --no-deps web npm run
build-storybook`. The smoke build; NOT in `make check` (too slow — human
  directive). It lands in CI instead (next bullet).
- **CI (`check.yml`):** one new step after `make check`, guarded on the
  token — `if: ${{ secrets.CHROMATIC_PROJECT_TOKEN != '' }}` — running
  `make chromatic`. New target:
  `make chromatic` — `docker compose run --rm --no-deps -e
CHROMATIC_PROJECT_TOKEN web npx chromatic --storybook-build-dir=storybook-static
--exit-zero-on-changes`, dependent on a prior `make storybook-build`.
  Why the CLI in-container and not the documented `chromaui/action`: the
  action assumes host Node; everything here runs through make + containers
  (AGENTS rule 1, WORKFLOW "every command is a make target"). Same product,
  same token. `--exit-zero-on-changes` because baselines do not exist yet —
  CI is advisory until the human accepts a baseline in Chromatic; revisit
  after the project is live (Open question).
- **Skip-guard convention:** every target starts with the Makefile's
  `skip_if_missing` on `frontend/.storybook/main.ts`, so a checkout without
  the config skips instead of failing (phase-0 rule; also keeps this branch
  green if rebased before merge order matters).
- `.PHONY` line gains `storybook storybook-build chromatic`.

### Housekeeping

- `.gitignore`: `storybook-static/` under the node section.
- `frontend/.prettierignore`: `storybook-static/` — prettier does not read
  `.gitignore` (its own header says so) and `prettier --check .` runs from
  `/app`; without this the build output fails lint.
- `frontend/eslint.config.mjs` `ignores`: add `storybook-static/` (same
  reason; today only `dist/` and `node_modules/` are ignored). Eslint does
  not parse `.tsx` in this repo at all (TS7 Go port has no JS API — the
  config's own comment), so **the real gates for stories are prettier
  (`make lint`) and `tsc --noEmit`** — tsc runs from the pre-commit hook when
  stories are staged; the implementer also runs
  `docker compose run --rm --no-deps web tsc --noEmit` before handoff. Note
  `.storybook/` is outside `tsconfig.include` (`src`, `tests`,
  `vite.config.ts`) — leave it out; SB loads those files itself.
- `tsc 7 × storybook types` is the one unverified risk. If tsc 7 chokes on
  SB 10's shipped `.d.ts`, the fallback is a `types`-only compromise decided
  with the human — not silently excluding SB types. Expected fine (SB ships
  compiled types; `skipLibCheck` is already on) — say so in the handoff
  either way.

### ADR — yes, a short one: `docs/adr/0043-storybook-component-workshop.md`

Decision and call (planner): **ADR, not just a task-file justification.**
Reasons: AGENTS.md's bar is "new _runtime_ dependency", and this adds none —
but the slice commits the repo to a build tool, a CI step and an external
service (Chromatic), which is exactly the kind of decision ADR-0010 and
ADR-0013 already cover (tooling with structural consequences). The boundary
also deserves ADR-grade permanence.

Content (~40 lines): Storybook 10.6 (unified package, react-vite) as the
component workshop for the 3.9 library; Chromatic for visual regression on
the story set; Code Panel as the source-viewing mechanism (Storysource
removed upstream in SB 9). **What it must never become:** a fourth UI-spec
artifact (ADR-0031 keeps three — SCREENS, Figma, UI_STATES); the variant
matrix stays in `UI_STATES.md`, stories mirror it and cite it, never
redefine it; stories are documentation, not tests (`make test-web` is
unaffected; portable-stories/vitest integration deliberately not adopted);
`storybook build` not in `make check`. Status: accepted; supersedes nothing.

## Files this slice owns

- `frontend/package.json`, `frontend/package-lock.json`
- `frontend/.storybook/main.ts`, `frontend/.storybook/preview.tsx` (new dir)
- `frontend/src/components/*.stories.tsx` (31 new; the `.tsx` component files
  themselves are 3.9's — untouched)
- `frontend/eslint.config.mjs`, `frontend/.prettierignore` (ignore additions
  only)
- `Makefile` (three targets + `.PHONY`), `.gitignore` (one line)
- `.github/workflows/check.yml` (the guarded Chromatic step)
- `docs/adr/0043-storybook-component-workshop.md` (new)
- `.tasks/chore-3.9-storybook.md` (this file)

**Not owned:** the 31 component sources, `docs/UI_STATES.md` /
`DESIGN_SYSTEM.md` / `COMPONENTS.md` (stories cite them, never edit them),
`compose.yaml` (no change — `run -p` needs none), `vite.config.ts`,
`tsconfig.json`, `ThemeToggle`.

**Stack note:** `feat/3.9-design-system-components` owns
`frontend/src/components/**`; this slice adds files there. Sequential after
3.9 merges (or same checkout while stacked) — no other in-flight slice
touches these paths.

## Acceptance

- [ ] `make storybook` serves all 31 components; every persistent prop axis
      value from DESIGN_SYSTEM §coded library has a named story (mirror the
      `components-{3a,3b}` test arms; matrix-test-only combinations too).
- [ ] Toolbar switches `theme` light/dark and a component visibly re-themes
      (tokens flip — verify e.g. `Button` primary, `Card` surface in dark).
- [ ] Code Panel shows the story's source for a component story (the
      Storysource acceptance, v10 form).
- [ ] The `@chromatic-com/storybook` addon loads (Visual Tests panel /
      no boot errors), `make storybook-build` succeeds in-container, and
      `storybook-static/` is ignored by git, prettier and eslint.
- [ ] CI: the Chromatic step exists, guarded on
      `secrets.CHROMATIC_PROJECT_TOKEN`, and `make chromatic` runs the CLI
      in-container against the prebuilt output. Without the token the gate
      is unchanged.
- [ ] `make check` green and not meaningfully slower (stories add prettier +
      pre-commit-tsc work only; no new test, no build in the gate).
- [ ] `tsc --noEmit` (strict) clean over the stories —
      `docker compose run --rm --no-deps web tsc --noEmit`.
- [ ] ADR-0043 written to the contract above; `make agents`-generated files
      untouched (no drift).
- [ ] No BUILD_PLAN tick — this chore has no task there (noted at the top).

## Handoff log

- planner — contract above; branch cut from `575c62f`. Facts verified
  2026-10-24: registry via in-container `npm view` (storybook 10.6.3 ·
  @storybook/react-vite 10.6.3 · @chromatic-com/storybook 5.6.0, peers
  `^10.6.0-0` · chromatic 18.13.3 · addon-storysource latest 8.6.14 /
  peers `^8.6.14` — removed upstream in SB 9, Code Panel is the successor),
  docs via ctx7 (`/storybookjs/storybook` MIGRATION.md + code-panel.mdx,
  `/chromaui/chromatic-docs` visual-tests-addon.mdx + configuration/cli.mdx).
  Theme mechanism read from `design/tokens/tokens.css` (`:root[data-theme]`,
  line 219) and `frontend/index.html`. **Hand off to `spydra-frontend`**,
  first file `frontend/package.json` (in-container install first — nothing
  type-checks until SB exists); Makefile/CI edits ride along in the same
  slice per the patterns quoted above.
- frontend — implemented, verified 2026-10-24. Installed in-container (all
  `^`-majors per ADR-0017): `storybook 10.6.3` · `@storybook/react-vite
10.6.3` · `@chromatic-com/storybook 5.6.0` · `chromatic 18.13.3` (CLI as
  devDep — `make chromatic` runs `npx chromatic` in the web container, per
  the contract's in-container-CLI call). **Addons list is string-form**
  (`addons: ["@chromatic-com/storybook"]`) — the contract's "object form
  only if needed" governs; no options needed (token flows via env, not
  in-band). 31 `*.stories.tsx` files, **143 stories**, one per persistent
  axis value plus exactly the matrix-test combinations (Modal
  confirm×submitting, LineChart 2-series×live, Tag removable×disabled,
  Spinner onBrand on a `bg-brand` patch); counts per component in the PR
  body. One deviation from the owned-files list, forced by `make check`:
  **`frontend/tests/design-system.test.tsx` edited** — its palette-guard
  inventory asserted components/ holds exactly 32 `.tsx` files; stories
  double it. The guard now excludes `*.stories.tsx` from the count but
  still scans them for raw palette classes (stories follow rule 6 too).
  Mechanical, intent preserved, noted here because the file was "not
  owned". Verification: `tsc --noEmit` strict **clean** over the stories —
  SB 10's shipped `.d.ts` and tsc 7 coexist fine, `skipLibCheck` already
  on, no exclusions needed (the contract's one flagged risk did not
  materialise). SB10 typed stories require `args` on any story whose
  component has required props — Skeleton/Tooltip needed args+render or
  args-with-children; caught by tsc, fixed. `make storybook-build`
  succeeds in-container (Vite build 1.2s + SB build, output
  `storybook-static/`, gitignored). `make storybook` served on
  127.0.0.1:6006 — curl 200, dev `index.json` reports 143 stories, zero
  errors in the log (in-browser addon/theme/code-panel checks are the
  reviewer's by the task file's own acceptance list). `make lint` green
  (prettier covers `.storybook/` and stories), `make test-web` **107/107
  unchanged**, full `make check` green, `make agents` zero drift. Deviations
  from contract: none besides the test file above; no BUILD_PLAN tick; no
  host installs. **Hand off to `spydra-reviewer`** (test agent follows the
  review per the umbrella's flow — this slice ships no component tests by
  directive; the design-system.test.tsx edit is a guard adjustment, not a
  new test).
- test — added `frontend/tests/stories.test.ts` (3 tests), verified
  2026-10-24. **The drift guard:** every `src/components/*.tsx` excluding
  `*.stories.tsx` and `ThemeToggle.tsx` must have a sibling
  `<Name>.stories.tsx`; every stories file must export ≥1 named story
  (`export const` beyond default/meta — the implementer's shape is
  uniformly `export const X: Story =` beside `export default meta`, 143/143,
  zero `export const meta`; the guard counts any `export const` except
  `meta`, so it stays honest under CSF's other spelling too). No count
  assertions (31/143 are today's numbers, not the contract — later slices
  add components and the guard must let them). **Palette-guard claim
  verified TRUE, not duplicated:** `design-system.test.tsx` "all 31 files
  scanned" scans `[...files, ...storyFiles]`, and `palette-guard.test.ts`
  walks all of `src/` recursively with `.tsx` in scope — stories are
  covered twice over. **Preview shape guard:** `globalTypes.theme.toolbar`
  must list `"light"` and `"dark"` (order-tolerant items-array capture) and
  the decorator must set `data-theme` on `document.documentElement`
  (accepts `setAttribute("data-theme")` — what the implementer wrote — or
  `dataset.theme`). Static regex, not import: preview is JSX-bearing TSX
  deliberately outside `tsconfig.include`; for config-of-config the shape
  is the contract (comment in the file says so). Suite **110/110**
  (107 + 3), `make lint` green. Mutations, all red then restored green:
  deleted `Tag.stories.tsx` → sibling test red; stripped story exports from
  `StatePill.stories.tsx` → zero-story test red; `preview.tsx`
  `"data-theme"` → `"x-theme"` → preview-wiring test red. **One pre-existing
  defect noticed, not fixed (outside owned files):** `make fmt`'s frontend
  leg is `prettier --write src` while `lint-web` checks `.` — a formatting
  slip in `frontend/tests/` or `.storybook/` can be seen by lint but not
  repaired by `make fmt` (hit it: new test needed in-container
  `prettier --write tests/stories.test.ts`). One-line fix in the fmt
  recipe when its owner next touches the Makefile. **Hand off to
  `spydra-reviewer`.**

## Open questions

- **`CHROMATIC_PROJECT_TOKEN` — the human's action.** Create the Chromatic
  project, put the token in GitHub secrets (and `.env` if wanted locally —
  it is a secret; `.env` is gitignored, `.env.example` gains a commented
  placeholder line naming it). Until then the CI step skips silently and
  that is correct.
- **Chromatic as gate vs advisor:** `--exit-zero-on-changes` is pinned for
  bootstrap; once the human accepts a baseline, decide whether unaccepted
  visual diffs should fail CI (drop the flag) — human's call, later.
- **Dark-theme Chromatic coverage** (duplicated stories or `--args`
  capture): deferred deliberately; toolbar covers human review.
- **tsc 7 × SB shipped types** — expected clean (`skipLibCheck` on);
  if not, escalate rather than exclude.
