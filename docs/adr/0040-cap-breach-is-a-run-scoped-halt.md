# 0040 — A URL-cap breach is a run-scoped halt, not a domain state

**Status:** Accepted · 2026-10-23
**Relates to:** [ADR-0002](0002-postgres-as-queue.md),
[ADR-0004](0004-stop-on-block.md), [ADR-0026](0026-claim-locks-the-domain-row.md)

## Context

Spec 004 §3 names faceted navigation as the trap that kills crawls: a
combinatorial URL space in which every URL looks legitimate. Reviewed
`deny_patterns` are the first defence and the dry-run (2.10) the second, but
a run can still walk into an unreviewed facet space, an endless calendar or
a relative-link loop. BUILD_PLAN 2.5 adds the backstop: a per-domain URL
cap, default 20,000, on `domains.url_cap` — placed on the domain, where
`max_depth` already lives, because it is the same kind of thing: an
operator-editable per-domain crawl shape.

What a breach does had to be decided, because the two existing halts are
both _domain_ halts: 1.11's broken-template halt moves the domain out of
`active`, and ADR-0004's 403 pause does the same. Neither fits here. A trap
is a template defect, not a site refusal — the site is serving exactly what
our (broken) discovery rules keep selecting. Halting the domain would tell
the operator the _site_ did something, when the thing that needs fixing is
the rule.

## Decision

**A breach halts the run, not the domain.** The enqueue that finds the
count at the cap signals it; the caller then, in one transaction, abandons
that domain's pending rows in that run and fails the run with the cap named
as the `stop_reason`. The domain row is untouched: it stays `active`, and
the next run's `(run, domain)` count starts at zero — below any cap — so
the next run starts clean by construction. Nothing to reset, no state to
clear; that is why the design is run-scoped rather than a domain state.

**What counts toward the cap.** Every `crawl_queue` row for the
`(run_id, domain_id)`, in any state. `UNIQUE (run_id, url_hash)` already
makes row count == distinct discovered URL count within a run, and
abandoned and failed rows still count because they are work discovery
produced. This is also what makes the count a durable breach flag: rows
within a run are never deleted, so once the count is at the cap every
further enqueue refuses without any new state.

**Enforcement is a count guard inside the guarded enqueue** — the same
statement that already refuses a halted domain or a finished run, under the
same `FOR SHARE`. That lock fences the _enqueue's_ guards, not the halt:
`halt_run` takes no domain lock and touches no locked row — it is fenced by
its own `state = 'running'` predicate on the run row, which every finish
path re-checks under the UPDATE's row lock, so a run that completed or
failed first is never failed under it. One round trip, no per-link check.
A batch is all-or-nothing: while the count is below the cap the whole
batch inserts (it may overshoot); at or past the cap nothing inserts. The
statement returns `(added, capped)`, `capped := count-after-insert >=
cap`, which is what tells the crawler to halt.

**The race, stated honestly.** Against ADR-0026's lesson — there, the
politeness guarantee silently failed twenty rounds out of twenty — this cap
is deliberately _not_ an exact invariant. Two concurrent enqueuers can each
see a count below the cap and both insert; the overshoot is bounded by one
batch per concurrent enqueuer, after which the count is at or past the cap
and every further enqueue refuses. Politeness is exact and lock-enforced
because a violation there is a broken promise to a host; a trap defence
with a fuzzy edge costs a bounded number of extra rows against a site that
is answering us, and the statement-snapshot race is the price of no
per-link round trip.

**The recording.** The run's state becomes `failed` — not `stopped`, which
is reserved for the operator's stop (2.7): a breach is system-initiated
against a template defect, and `failed` with a reason is what tells the
operator to act. `stop_reason` names the cap and the host exactly
(`url cap exceeded: {cap} urls queued for {host}`), and `stats` is
computed by the same `_STATS` shape as every other run finish, so
`pages_abandoned` records the work the breach prevented. The terminal
state **and** the abandoned count together are what make it "not a clean
finish"; either alone is weak. Because `state = 'running'` guards the
transition, the halt is first-signaller-wins: the in-flight tail after a
breach (bounded by `max_concurrency`) re-signals, changes nothing and logs
at debug.

**Seeds are not capped.** The loader's own enqueue of the operator's
hand-given seed list is untouched. A seed set above the cap surfaces as a
breach on the first discovery enqueue, or completes uncapped if nothing
discovers — stated, not defended against.

## Consequences

- A breached run can never finish `completed` with pages unaccounted: the
  abandon and the failure commit together, and a `finish_if_drained` that
  races the halt re-checks `state = 'running'` on the run row and refuses.
- The halt is **one transaction, two statements** (abandon, then the
  guarded failure), not the single CTE first sketched: PostgreSQL's
  data-modifying CTEs all read one snapshot and cannot see one another's
  writes, so a stats subquery inside the failure CTE would count the
  abandoned rows as still `pending` and write `pages_abandoned = 0` —
  exactly the clean finish this ADR forbids. The second statement in the
  same transaction sees the first's writes; atomicity against worker death
  is the transaction's, unchanged.
- `run_events` does not exist yet (2.8). The seam: 2.8 adds a `run_state`
  event row for the breach so SSE clients see it; everything 2.5 records —
  the run row, its `stop_reason`, its stats, one error line — is what 2.8
  replays.
- **Cost: the cap is counted per run, not per domain-history.** A domain
  whose every run breaches will breach again on each run until the rule is
  fixed; each breach costs one crawl to the cap. That is the correct bill —
  the alternative is a domain-level odometer the operator cannot reset
  without SQL.
- **Cost: an explicitly allowed calendar is not warned about.** The
  calendar reject is escaped by `allow_patterns` (the operator's reviewed
  yes, spec 004 §1 rule 3); a broad allow implicitly permits an endless
  calendar, and the cap is then the only backstop. Making that visible is
  the dry-run's job (2.10), not the crawl's.
- Multi-domain runs do not exist (every run-creation path is 1:1 today);
  if they ever do, the halt's run-level UPDATE needs a per-domain stop
  decision (2.7's seam).

## Alternatives considered

- **Pause the domain, as ADR-0004 does on 403s.** Wrong diagnosis: a 403
  is the site refusing; a trap is our rule misfiring. A paused domain also
  needs resuming before the next run, which converts an operator's rule fix
  into two operator actions.
- **Fail the domain, as 1.11's broken-template halt does.** Same
  misdiagnosis, and it hides the one fact that matters — the run was
  stopped by a cap, not by broken extraction.
- **Exact enforcement (serialize enqueuers, or count per link).** Either
  costs a round trip per link or a lock queue on every enqueue, to prevent
  an overshoot bounded by one batch per concurrent enqueuer against a site
  that is answering. ADR-0026 spends that exactness where politeness lives;
  a trap backstop does not need it.
- **A `capped` flag on the run or domain row.** New state, and redundant:
  the count itself is durable and monotonic within a run, so refusal after
  breach is self-healing with no flag to keep true.
