# 0002 — Postgres is the queue and the datastore

**Status:** Accepted · 2026-10-15

## Context

The crawler needs a work queue holding URLs to fetch, and it needs to record
what it found. The obvious instinct is a message broker — Kafka, RabbitMQ,
SwiftMQ — with Postgres behind it for results.

The constraint that decides this is **politeness**. Each domain has state: the
time it is next eligible to be fetched, its current backoff, its consecutive
failure count, its robots.txt directives. The scheduler's core question is
"which domain may I fetch from right now", answered against that state.

## Decision

**Postgres is both the queue and the database.** Dequeue is
`SELECT … FOR UPDATE SKIP LOCKED` inside the same transaction that writes the
result. No broker, no Redis, no second datastore.

The queue sits behind a `Frontier` port with a Postgres adapter, so the
decision is reversible if the ground ever shifts.

## Consequences

- **Dequeue and result-write are atomic.** With a broker, the crawled row and
  the queue offset live in different systems, which is a dual-write problem:
  on a crash you get either duplicate crawls or lost URLs. Here a crash rolls
  back and the row returns to `pending` when its lock expires.
- **Politeness state lives next to the queue**, so the eligibility check is a
  join rather than a lookup in a second system.
- **Workers scale by replica count** without violating per-domain limits,
  because the limit is enforced in the database, not in process memory.
- **Operationally there is one thing to run.** For a single-user local tool
  that matters more than throughput headroom.
- **Cost:** Postgres will not match a broker's throughput, and a busy queue
  means index churn and vacuum pressure on `crawl_queue`. At 1,200 domains
  and tens of thousands of URLs per run this is nowhere near the limit, but
  it is the thing that would eventually break. The mitigation is the
  `Frontier` port, not premature optimisation.

## Alternatives considered

**Kafka.** Rejected. Its partitioning model fights the requirement: it gives
ordered partitions and consumer offsets, not per-key rate limiting, so the
per-domain scheduler would be maintained externally anyway — the broker buys
nothing and costs a dual-write problem.

**Redis as a queue.** Rejected. Same dual-write problem, plus a second
datastore to run and back up, in exchange for throughput that is not needed.

**A dedicated frontier (Frontera, or hand-rolled).** Rejected. Frontier
designs exist because web-scale crawlers need a distributed, disk-backed URL
store across many machines. One machine and 1,200 domains do not generate the
design pressure that justifies one.
