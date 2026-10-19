# fix/scaffold-copy-phase-3

**Task:** none — a defect in phase-0 scaffold copy ·
**Spec:** docs/BUILD_PLAN.md phase 1 preamble and phase 3; specs/010 §2 ·
**ADRs that constrain this:** 0015 (one origin at the edge), 0025
(`UI_STATES.md` is the state authority)

Filed late. The reviewer pass on `feat/phase-1-foundation` found this branch
merged with no handoff file, which AGENTS.md § Repository layout and ADR-0022
§2 both require — and it was the only silent one on a branch where every
other deviation was declared. Written now rather than argued away.

## Files this slice owns

- `frontend/src/App.tsx` (copy only)
- `.tasks/fix-scaffold-copy-phase-3.md` (this file)

## What and why

The phase-0 placeholder read "domains, templates and runs arrive with the
**phase 1** schema". The phase-1 schema landed with 1.1 and there was still
nothing to see, because the screens are phase 3 — `3.9` builds the component
set, `3.10` onward builds Domains, Review and the run monitor, and phase 1's
own preamble says "No UI, no model". The copy set an expectation the build
plan never made, and it cost a round trip to ask about, which is the defect.

It also now says on the page to use the edge at `127.0.0.1:8080` rather than
the Vite port. `VITE_API_BASE` is deliberately empty because every call is
same-origin through the edge (ADR-0015, spec 010 §2), so a browser on `:5173`
sends `/api/*` to Vite, which has no proxy. Harmless while the scaffold makes
no calls; broken from `3.10`.

## Decisions

- **No Vite proxy was added.** It would be a second routing path that can
  drift from `docker/Caddyfile`, and TESTING.md §1 puts e2e through the edge
  precisely because that routing is the most likely thing to be
  misconfigured. One origin, described in one place.
- **Copy only.** No component, no state, no token, so ADR-0025 is untouched
  and `UI_STATES.md` has nothing to say about it.

## Acceptance

- [x] The placeholder names phase 3 and `3.9`, not phase 1
- [x] The page says which port to use, and why
- [x] `prettier --check` clean — the first draft was not, and `lint-web` runs
      `prettier --check .`, so it would have failed `make check`

## Handoff log

- frontend — copy rewritten; prettier run against the pinned 3.9.10 before
  committing.
- reviewer — the finding that produced this file. Nothing further to review
  in two paragraphs of copy.
- integrator — `make check` green on the consolidated branch.
