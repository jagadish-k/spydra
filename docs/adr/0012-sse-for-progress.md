# 0012 — Server-Sent Events for live progress

**Status:** Accepted · 2026-10-15

## Context

The run monitor shows a crawl as it happens: per-domain progress, throughput,
a live log. The operator starts a run and walks away, so the browser will
sleep and the laptop will close.

## Decision

`GET /api/runs/{id}/events` returns `text/event-stream`. Control actions —
pause, stop — are ordinary `POST` endpoints.

Every event carries an id. On reconnect the browser sends `Last-Event-ID` and
the server **backfills from the run's event log** rather than resuming from
live.

## Consequences

- Progress streaming is one-directional, which is exactly what SSE is for.
  WebSockets would add a protocol, a heartbeat and a reconnection strategy to
  hand-roll.
- Reconnection is native to the browser's `EventSource`.
- **Backfill is non-negotiable.** Without it a slept browser shows a gap, or
  worse a frozen progress bar that reads as a stalled run. This requires the
  server to retain a bounded per-run event log, which is a real piece of work
  and not an afterthought.
- **Cost:** SSE is HTTP/1.1-limited to six connections per origin, which is
  irrelevant here with one user and one stream. The event log is extra state
  to retain and expire.
