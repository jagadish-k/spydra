# 0030 — An empty extraction only counts as a regression if the page once worked

**Status:** Accepted · 2026-10-19
**Amended by:** [ADR-0037](0037-empty-means-nothing-substantive.md) (the prior is read as
`content_hash IS NOT NULL`);
[ADR-0039](0039-listing-pages-are-not-extraction-verdicts.md) (listing pages
are outside both counts)
**Amends:** [spec 003](../specs/003-extraction.md) §3,
[spec 001](../specs/001-domain-model.md) §1 (`unknown_pages.reason`),
[`TESTING.md`](../TESTING.md) §2
**Relates to:** [ADR-0007](0007-append-only-observations.md) (append-only
observations), [ADR-0027](0027-no-required-fields.md) (emptiness is the only
failure signal)

## Context

[ADR-0027](0027-no-required-fields.md) removed required fields and re-based
the `broken` threshold on the **`empty_extraction` rate**: a 200 response from
which no field resolved. Past 20% of a domain's pages in one run, the domain
moves to `broken` and crawling stops for it mid-run. That is the detector for
the failure spec 003 §3 calls the most important — a redesign that produces no
error and no crash, just wrong data.

A **soft 404** produces exactly the same signal. A catalogue with dead links
returns HTTP 200 with a "product not found" page and no product content, which
is ordinary: one of the example sites in `docs/TARGETS.md` does it. Per page,
a soft 404 and a redesigned page are indistinguishable — both are a 200 from
which nothing resolved.

So a healthy domain with more than 20% dead links halts itself on every run
and reports a redesign that never happened. And because ADR-0027 made
emptiness the _only_ signal, there is no second mechanism to fall back on.

The tempting fixes all require knowing what a page _means_. A title containing
"not found" is locale- and markup-dependent. A missing product container is
template-dependent, and a redesign is precisely when the template stops
matching. Neither is deterministic, and spec 003's whole design is a
deterministic chain.

## Decision

**An `empty_extraction` counts toward the `broken` threshold only for a page
that has a prior non-empty observation.**

```
regression(page)  ⇔  empty_extraction(this observation)
                     AND ∃ an earlier observation of this page
                         whose extraction was non-empty

broken(domain, run) ⇔ count(regression) / count(pages crawled) > 0.20
```

Nothing else changes. `empty_extraction` is still the reason the page carries
into `unknown_pages`, and every empty page still reaches the review inbox. The
only question this answers is which of them is **evidence of a regression**.

The reasoning is that a regression is a _change_, and a page that has never
yielded anything cannot have changed. A dead link was always dead; the
append-only observation history (ADR-0007) already knows which is which, so
this needs no new data, no heuristic and no content understanding — only a
query the schema already supports (`page_observations (page_id, observed_at
DESC)`, spec 001 §1).

### The first run has no priors, and that is the correct answer

On a domain's first run nothing has a prior observation, so the threshold
cannot fire. That is not a hole:

- An empty extraction on a first run means **the template never worked**, not
  that the site changed. The right destination is `awaiting_approval` — back
  through review — not `broken`, which means "this used to work".
- So: a first run in which more than 20% of pages are empty moves the domain
  to `awaiting_approval` with that reason, and the operator sees a template
  that was approved against samples and fails against the catalogue.

That distinction was absent before this ADR, and it is the more common failure
in practice: a template approved on three sample pages meeting a catalogue
with five page layouts.

## Consequences

- **A catalogue with dead links stays `active` and keeps crawling.** The dead
  pages accumulate in the inbox as `empty_extraction`, where they are a
  content problem for the operator rather than a crawl-halting one.
- **A genuine redesign is caught as sharply as before**, and arguably more
  sharply: a redesign hits pages that _did_ extract, which is exactly the set
  this counts. The soft 404s that used to dilute — or falsely trigger — the
  ratio are now excluded from both the numerator and the signal.
- **Two failure modes are now distinguishable** that previously shared one
  state: "this used to work and stopped" (`broken`) and "this never worked"
  (`awaiting_approval`).
- **`validation_failed` is removed from the `unknown_pages.reason`
  vocabulary.** ADR-0027 stopped it firing and `docs/SCREENS.md` still
  offered it a row and an action; spec 001 §1 now carries the authoritative
  list, as it does for `domain_state`.
- **Cost: a redesign that lands before any page ever extracted is invisible
  to this threshold.** It is caught at approval instead, which is a different
  screen and a slower loop. Accepted: the alternative is halting domains for
  having dead links, which is the common case rather than the rare one.
- **Cost: the threshold now needs the observation history**, so it is a join
  rather than a count over the current run. At the expected volume this is
  cheap, and the index spec 001 §1 already defines is the one it needs — but
  it does mean the detector cannot run on a database that has been purged of
  history, which nothing does today and nothing should.
- **Cost: a page that alternates between extracting and not** — a flaky
  renderer, an intermittent soft 404 — counts as a regression every other
  run. That is noisy rather than wrong, and the per-field diff in `5.6` is
  where it becomes legible.

## Alternatives considered

**Detect soft 404s by content.** Rejected. "Not found" in the title or an
`h1`, a short body, a missing product container — all locale-, markup- and
template-dependent, and the template is the thing that has stopped matching
when a redesign happens. It would put a guess at the centre of the one
detector that has to be trustworthy.

**Trust HTTP status.** Rejected as a non-answer: a soft 404 is a 200 by
definition. That is what makes it soft.

**A separate `unknown_pages.reason` for it.** Rejected — not because another
reason would be wrong, but because assigning it requires the detection above.
The reason is not the hard part.

**Exclude pages whose URL was discovered but never successfully crawled.**
Rejected as a weaker version of this decision: it conflates "never crawled"
with "crawled and yielded nothing", and the second is the case that matters.

**Lower the threshold and accept false halts.** Rejected. A false `broken`
stops a domain and needs human attention to resume (ADR-0004's stated cost),
so tuning the number trades one silent failure for a loud recurring one.
