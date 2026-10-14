<img src="design/logo/spydra-lockup-horizontal.svg" alt="Spydra" width="200" />

A single-user, locally-hosted crawler that discovers and extracts structured
product data from bespoke supplier and e-commerce sites, using a local LLM to
**propose** extraction rules that you approve before any domain goes live.

The model proposes once per template. It never runs during a crawl.

---

## Status

**Design complete, implementation not started.** This repository currently holds
the architecture blueprint, the design system, and static mockups of all nine
screens. No application code yet.

---

## Repository layout

```
docs/
  ARCHITECTURE.md    System design: scheduler, extraction chain, concurrency,
                     deployment, failure modes, build plan. Source of truth.
  DATA_MODEL.md      Postgres schema and the reasoning behind its shape.
  DESIGN_SYSTEM.md   Tokens, typography, components, anti-patterns.
  SCREENS.md         What each screen is for and what it contains.
  BRAND.md           Logo construction, variants, usage rules.

design/
  tokens/            tokens.css (runtime) · tokens.json (W3C, for Figma)
  logo/              Six SVG variants + the generator that produces them
  mockups/           Static reference implementation of all nine screens

tailwind.config.ts   Maps semantic tokens to Tailwind; replaces the default
                     palette so raw colour classes fail to compile.
```

## Viewing the mockups

```sh
open design/mockups/index.html
```

No build step and no server — they are plain HTML and open straight from disk.
The theme toggle in the top bar persists per browser; **light is the default**
unless your OS asks for dark on a first visit.

Start at `foundations.html` for the design system, or `template-review.html` for
the screen that matters most.

## Regenerating the logo

```sh
python3 design/logo/build_logo.py
```

All six variants derive from one 64×64 lattice. Edit the geometry constants at
the top of that file and every variant follows — which is what keeps the favicon
a true subset of the mark rather than a lookalike that drifts.

---

## The shape of the system, in short

**Postgres is the queue.** Not Kafka. Politeness is per-domain state (next
eligible time, backoff, token bucket) and a broker gives you ordered partitions,
not per-key rate limiting — so you would maintain the scheduler externally
anyway. More importantly, a Postgres queue makes dequeue and result-write
atomic; a broker splits them across two systems and hands you a dual-write
problem for no benefit.

**Three worker pools, one politeness gate.**

| Pool | Concurrency | Per-host limit |
| --- | --- | --- |
| Static pages | 8–16 | 1, with a 2 s gap |
| Rendered pages | 3 contexts | 1, same gate |
| Assets | 16–32 | 4–6, with a 200 ms gap |

Assets parallelise within a host because an image is a static byte range,
usually cached, costing the origin almost nothing — six concurrent image fetches
is what a real browser does to render one page. A product page is a dynamic
request that costs the origin CPU and reads as a crawl pattern in their logs, so
it stays sequential. Pages are gated in Postgres because the limit must hold
across worker replicas; asset concurrency is an in-process semaphore because a
loose limit is not a correctness concern.

**Extraction is a chain, cheapest rung first:** structured data (JSON-LD,
microdata) → approved category selectors → LLM-proposed selectors → the unknown
queue. Every proposal is **verified deterministically** against the real DOM
before you ever see it, which turns a probabilistic suggestion into a checked
candidate.

**Templates are versioned, never edited in place,** and keyed on
`(domain, url_pattern)` rather than domain alone. Every observation records the
template version that produced it — without that, a price change caused by your
own selector edit is indistinguishable from a real one, and the distinction
cannot be retrofitted.

**Observations are append-only.** Current state is a view. Only raw HTML is
purged, on a 7-day TTL.

**Getting blocked stops the crawler rather than triggering a retry.** A retry
loop against a site that has decided to block you is how a temporary block
becomes a permanent one.

## Deployment

Three containers — `db`, `api`, `worker` — plus **`llama-server` running natively
on the host**. Docker Desktop on macOS has no Metal GPU passthrough, so a
containerised model would run on CPU inside the VM and lose most of the Ultra's
advantage. Containers reach it at `host.docker.internal:8080`.

`/data` is a bind mount, not a named volume: you want images and HTML visible in
Finder, backed up by Time Machine, and surviving `docker compose down -v`.

## Known open questions

- **JS rendering prevalence.** Both fetch adapters ship in phase 1, so this no
  longer gates the design — but it sizes the run. The rendered pool caps at 3
  contexts against 8–16 static workers, so if most domains need rendering, page
  throughput drops roughly 4×.
- **Supplier data shape.** "Vendor information, supplier details" may be
  structured tables on some sites and free prose on others. JSONB absorbs either,
  but querying consistently across suppliers needs a normalisation pass.
- **Review throughput, not technology, is the constraint.** At one template per
  domain and six domains a month, 1,200 domains is roughly sixteen years away.
  Batch review is built in from phase 3 for this reason; tiered coverage stays
  unbuilt until the coverage report shows the backlog growing faster than you
  clear it.
- **Legal posture.** Crawling bespoke supplier catalogues raises terms-of-service
  questions separate from the technical ones. Worth checking the ToS of the first
  few targets — a real input to which domains get onboarded.
