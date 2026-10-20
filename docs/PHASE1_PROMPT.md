<!-- Kept as the brief this phase started from, matching PHASE0_PROMPT.md's
     convention. Two of its instructions have since been superseded by
     BUILD_PLAN.md, which is authoritative: the three parallel lanes
     (A/B/C) are abandoned — phase 1 is strictly linear — and nothing in the
     build depends on real target sites, which 1.4's local fixture site
     replaced. Read BUILD_PLAN § Phase 1 for the current order. -->

# Starter prompt — phase 1

Phase 0 is merged into `develop`. Phase 1 is the first phase with real
engineering risk in it: the scheduler and the data model are the two things
most expensive to get wrong, and both are proven here with no UI and no model
in sight.

Paste the block below into a fresh session opened at
`~/projects/personal/spydra`. Launch details per tool — which agent to start
in, where the roles are generated — are in
[`PHASE0_PROMPT.md`](PHASE0_PROMPT.md § Starting it in each tool); nothing
about that has changed.

**One thing to do before you paste it:** decide whether you are ready to pick
the three target domains. Task `1.3` is a human decision with legal
consequences and the prompt is written to stop and ask for it. If you would
rather choose first, write `docs/TARGETS.md` yourself and tell the session it
is already done.

---

```
We are starting Phase 1 of Spydra. Phase 0 is merged into develop: the gate,
the six services, both migration chains, the generated-artifact chain and CI
all exist and are proven. There is no domain logic yet.

Read these first, in this order, and do not skip any:
  1. AGENTS.md                      — the 18 hard rules, stack, commands
  2. docs/WORKFLOW.md               — branches, the two gates, the agent team
  3. docs/BUILD_PLAN.md § Phase 1   — the twelve tasks and the exit criterion
  4. docs/specs/001-domain-model.md — the schema and the lifecycle
  5. docs/specs/002-scheduler.md    — the frontier, the politeness gate,
                                      the render path
  6. docs/specs/003-extraction.md   — the chain, transforms, validation
  7. docs/TESTING.md § 2            — what must be tested, non-negotiable

Then the ADRs those name, at minimum 0002 (postgres as the queue), 0003
(three pools one gate), 0004 (a block stops the crawler), 0007 (append-only
observations), 0008 (ports and adapters) and 0016 (the render sidecar).

Also read .tasks/chore-phase-0-audit.md. Five findings are filed and not
fixed (F5, F7, F9, F10, F11). None blocks phase 1. Do not fix them here, and
do not rediscover them as if they were new.

STOP BEFORE ANY CODE — task 1.3 is mine, not yours.

1.3 picks the first target domains: two static, one JS-rendered, recorded in
docs/TARGETS.md with each one's robots.txt and terms. Choosing which real
websites this crawler points at is a decision with legal consequences and it
is not yours to make. Propose candidates with evidence if you like — what
their robots.txt says, whether the terms forbid automated access, whether the
product pages are server-rendered — but do not write TARGETS.md and do not
record a choice until I have confirmed it. 1.4 depends on 1.3, and most of
the later tests depend on 1.4, so expect to pause here.

Everything else in the phase can start before that pause resolves.

HOW TO RUN IT

Phase 1 is not phase 0 — there is genuine parallelism here, and this is the
first real test of the handoff in ADR-0022. 0.17 proved it on a hello-world,
which proves the mechanism and nothing about the stress.

Start with 1.1 and 1.2 on one branch, sequentially. They are the foundation
every other task builds on and nothing should run beside them.

After those land, three lanes have disjoint file sets and can run in
parallel, declared in their task files before any of them starts:

  lane A  scheduler   1.5, 1.6, 1.11   backend/spydra/scheduler/
                                       backend/spydra/adapters/postgres/
  lane B  fetchers    1.7, 1.8         backend/spydra/adapters/http/
  lane C  extraction  1.9, 1.10        backend/spydra/extraction/

1.12 is last and is small. 1.3 and 1.4 sit outside the lanes and unblock the
fixtures everything in lane C wants.

Lane A is the one to watch. If two lanes must touch the same file, they were
one lane — say so and sequence them rather than resolving a conflict later.

SIX THINGS I CARE ABOUT MORE THAN SPEED

  - The politeness tests assert on OBSERVED FETCH TIMESTAMPS, not on mocks.
    TESTING §2 says this and it is the single most gameable requirement in
    the project. A test that fakes the clock and asserts the gate "would
    have" waited passes while the crawler is rude to a real supplier. Two
    workers against one domain means two real connections and real elapsed
    time. The Clock port exists for unit-testing logic; it is not a licence
    to simulate the thing this system exists to guarantee.

  - The claim query is correct under concurrency or it is nothing. FOR
    UPDATE SKIP LOCKED, one transaction, two real workers, and a test that
    actually races them. A single-connection test of a concurrency primitive
    proves only that the SQL parses.

  - Both fetchers ship in this phase, behind one port. A port with one
    implementation is an untested abstraction. When 1.8 lands, 1.7's tests
    should need no changes — if they do, the port is wrong, not the test.

  - content_hash is computed over NORMALISED fields. Hash the raw markup and
    every whitespace change looks like a price change, which defeats the
    entire point of append-only observations.

  - 1.12's YAML loader is scaffolding with a known end date — 3.2 deletes it.
    Build the smallest thing that lets a domain be configured without a UI.
    Do not give it a schema, a validator, an inheritance model or anything
    else someone could grow attached to.

  - A block stops the crawler. Three consecutive 403s pause the domain and
    abandon its queue. There is no retry-through, no "just one more", no
    exception for testing. If you need to exercise the path, exercise it
    against a fixture.

Start by writing .tasks/<branch>.md using the template in WORKFLOW §3, with
the Phase 1 exit criterion copied from BUILD_PLAN.md. Then work the tasks,
ticking each in BUILD_PLAN.md as its definition of done actually holds — not
when the code exists.

Before you write anything, tell me:
  - the lane plan and the file sets each lane claims
  - your target-domain candidates with the robots.txt and terms evidence,
    as a proposal I confirm or reject
  - anything in Phase 1 you think is wrong, missing or out of order
  - any decision you hit that no ADR covers

If a task needs a decision that is not in docs/adr/, stop and write the ADR
first — rule 1, not a formality.
```

---

## Why this prompt differs from phase 0's

**It carves out `1.3` and refuses to do it.** Phase 0 had no decision an agent
could get ethically wrong. Phase 1 opens by choosing which real websites get
crawled, and an agent that picks three plausible supplier sites and writes
them into `TARGETS.md` has made a legal decision on the operator's behalf
while appearing to be helpful. The prompt names it, hands it back, and still
lets the agent do the research that makes the choice easier.

**It plans lanes instead of a sequence.** Phase 0 was one branch because
there was nothing to parallelise. Phase 1 has three genuinely disjoint file
sets, and ADR-0022 says parallel work is safe only across declared, disjoint
sets — so the prompt asks for that declaration up front rather than
discovering the overlap in a merge.

**It pre-empts the one test everybody fakes.** Politeness is the guarantee
this system exists to keep, and it is the easiest thing in the codebase to
assert dishonestly. Naming the specific failure — a mocked clock proving the
gate "would have" waited — costs two sentences and is worth more than the
rest of the prompt.

**It says what not to build.** The YAML loader has a deletion date in the
build plan, and scaffolding that acquires a schema and a validator stops
being deletable. Saying so before it is written is cheaper than arguing about
it in review.

**It tells the agent what is already known-broken.** Five audit findings are
filed and deliberately unfixed. Without that line, a thorough session
rediscovers them, reports them as new, and either fixes them out of scope or
spends a round trip asking.
