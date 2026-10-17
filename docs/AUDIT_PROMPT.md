# Starter prompt — phase 0 audit and the UI_STATES wiring

Phase 0 is complete and ticked through `0.17`. Before phase 1 starts, two
things are worth an hour: checking that the ticks are true, and wiring
`docs/UI_STATES.md` into the process that is supposed to read it.

Paste the block below into a fresh session of whichever tool you are using,
opened at `~/projects/personal/spydra`. Start in `build` (OpenCode v2) or the
default primary agent; the prompt holds itself back from writing until you
answer.

---

```
Phase 0 of Spydra is complete and every task is ticked through 0.17. I want
an audit before phase 1 starts. Assume nothing in the tick marks is true
until you have re-run the thing it claims.

Read these first, in this order:
  1. AGENTS.md                      — the 18 hard rules, stack, commands
  2. docs/BUILD_PLAN.md § Phase 0   — every task's definition of done
  3. docs/UI_STATES.md              — the UI state matrix. This is the
                                      authoritative UI spec and it is newer
                                      than SCREENS.md and specs/006
  4. docs/WORKFLOW.md               — the gates and the agent roles
  5. .tasks/chore-phase-0-scaffold.md — what the phase 0 session recorded,
                                        including what it deliberately did
                                        not do

Then read the ADRs those name, at minimum 0010, 0013, 0015, 0017, 0018,
0021 and 0022.

Work on one branch: chore/phase-0-audit. Use spydra-reviewer for the reading
— it is read-only by design and this is a review, not a rewrite. Use
spydra-ops and spydra-bff only once the findings are agreed.

PART A — is phase 0 actually done?

For each task 0.1 to 0.17, decide from evidence rather than from the tick.
Re-run the proof the task names. Report each as PROVEN, UNPROVEN or BROKEN
with the command you ran and what came back. I care most about these five,
because each one fails silently:

  - 0.6  SSE streams unbuffered through the edge. Assert on arrival GAPS,
         not on the payload. A batched response contains the right bytes.
  - 0.7  The BFF role cannot write `crawl`. Prove it from a fresh volume,
         not from a database someone already migrated by hand.
  - 0.13 Both migration chains cycle. `make migrate` then `make migrate-down`
         then `make migrate` again, from empty.
  - 0.14 The generated-artifact chain detects drift. Hand-edit one generated
         file and confirm `make check` fails; revert it.
  - 0.12 The palette guard. Add `bg-red-500` to a component and confirm the
         test fails; remove it.

Also check the gate itself still bites: a long commit subject rejected, a
staged `.env` rejected, a direct push to develop refused, and a hand-edited
file under .claude/agents/ rejected.

PART B — the UI_STATES wiring, which is the actual gap

`docs/UI_STATES.md` is referenced by nothing. Not BUILD_PLAN.md, not
docs/specs/006-frontend.md, not SCREENS.md, not the spydra-reviewer or
spydra-frontend role. Its own §6 says the reviewer reads it to know what is
missing and that phase 3 components are built against the matrix rather than
against a populated screenshot. None of that is wired, so phase 3 will be
built against the mockups and the matrix will be discovered afterwards.

Propose the smallest set of edits that makes the matrix binding:
  - docs/specs/006-frontend.md — it currently names design/mockups/ as THE UI
    specification. Decide what it names now, and say so explicitly.
  - docs/BUILD_PLAN.md phase 3 — the UI tasks should carry state coverage in
    their definition of done, per UI_STATES §6.
  - docs/agents/spydra-reviewer.md and spydra-frontend.md — the reviewer
    needs to read the matrix; the frontend role currently says to match the
    HTML mockups exactly.
  - docs/SCREENS.md — a pointer, so the two files are not read in isolation.

Remember docs/agents/ is canonical and `make agents` regenerates the four
adapters; never edit a generated copy.

Two specific things UI_STATES asserts that need a home in the build plan:
  - skeleton heights are asserted against --sp-row-comfortable in a test,
    because a wrong-height skeleton is a layout jump no screenshot catches
  - the SSE reconnect path gets a test that drops the connection and asserts
    backfill from Last-Event-ID — phase 3 acceptance, not phase 5 hardening

PART C — loose ends

`docs/UI_STATES.md`, `design/tokens/tokens.css` and
`.tasks/design-figma-states.md` landed in commit b5d10cb, outside the phase 0
branch flow and with no task file. Check two things about that commit: that
the new tokens in `tokens.css` actually reach the frontend (`theme.css`
imports `tokens.css`, so they should — confirm it rather than assume), and
that nothing in it bypassed a gate.

`.tasks/design-figma-states.md` records the Figma side and lists where the
Figma file still disagrees with UI_STATES. Read it for context, but do not
act on it in this branch — it is design work, not code.

Before you change anything, tell me:
  - the PROVEN / UNPROVEN / BROKEN table for 0.1–0.17
  - your proposed UI_STATES wiring edits, as a diff plan rather than prose
  - anything in UI_STATES.md you think is wrong or unbuildable, and any
    decision you hit that no ADR covers

If a finding needs a decision that is not in docs/adr/, stop and write the
ADR first — rule 1, not a formality.
```

---

## Why this prompt is shaped this way

**It refuses to trust the ticks.** A tick is a claim made by the session that
wrote the code. The five tasks it singles out are the ones whose failure mode
is silence: buffered SSE looks like working SSE until a human watches a run,
and a missing grant looks like nothing at all until the BFF writes to `crawl`.

**It separates the audit from the fix.** Part A is read-only and belongs to
`spydra-reviewer`, whose whole value is that it did not write the code. Part
B is the only part that changes the repository, and it is bounded to four
files plus the regenerated adapters.

**Part B is the real reason to run it.** Phase 0 looks sound. The gap is that
the most rigorous UI document in the repository is wired to nothing, and
phase 3 is where that becomes expensive to undo.
