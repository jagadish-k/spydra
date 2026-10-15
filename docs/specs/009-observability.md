# 009 — Logging, metrics and operational surfaces

**Ongoing** · depends on 001

One operator, one machine, no alerting stack. Observability here means: when
something goes wrong, the answer is reachable in under a minute. No Prometheus,
no Grafana, no tracing backend.

---

## 1. Logging

`structlog`, JSON to stdout, collected by `docker compose logs`.

Every log line in a crawl path carries: `run_id`, `domain`, `url`,
`strategy`, `attempt`. A line without the context needed to act on it is
noise.

| Level | Use |
| --- | --- |
| `error` | Something needs the operator: a domain paused, a model failure, disk below threshold |
| `warning` | Degraded but handled: backoff applied, validation below threshold, asset rejected |
| `info` | Lifecycle: run started/finished, domain state change, template approved |
| `debug` | Per-page detail. Off by default; `LOG_LEVEL=debug` per service |

**Do not log at `info` per page.** A 10,000-page run makes the log useless.
Per-page detail is `debug`, and the live log in the UI comes from SSE, not
from scraping stdout.

Never log: full HTML bodies, the user's email beyond the configured
User-Agent, or credentials of any kind.

## 2. Metrics

Counters and gauges kept in Postgres, not a metrics backend. The reports in
spec 005 §Reports *are* the metrics layer, and they are queries.

Per run, rolled into `runs.stats` on completion:

```json
{ "pages_crawled": 3841, "pages_failed": 232, "pages_changed": 1284,
  "assets_downloaded": 8104, "asset_bytes": 2254857830, "dedupe_rate": 0.31,
  "by_strategy": {"structured": 412, "selector": 3201, "failed": 228},
  "by_domain": {"orbis-components.nl": {"crawled": 2771, "failed": 3, "429": 0, "403": 0}},
  "validation_pass_rate": 0.941,
  "duration_s": 3842 }
```

`GET /api/reports/politeness` reads these. It is the operator's evidence that
the crawler behaved, and the first place to look after a block.

## 3. The surfaces that matter

Three things silently stall this system. Each has a dedicated surface:

| Failure | Surface |
| --- | --- |
| Unreviewed template queue grows | Amber badge in the sidebar, visible from every screen |
| `llama-server` dies | Red dot in the sidebar footer; `/api/health` |
| Disk fills | Free space in the sidebar footer; pre-run check refuses to start |

And the one that produces no error at all — **silent extraction failure** —
is surfaced by the extraction-health report and the `broken` domain state.
That is the failure that corrupts a dataset quietly, which is why validation
is mandatory per field rather than optional.

## 4. Pre-run checks

`POST /api/runs` refuses, with a problem detail naming the cause, when:

- free space on `/data` is below 5 GB
- the database is unreachable
- no domain in the selection is `active`

It does **not** check `llama-server` — the model is not in the crawl path.

## 5. Acceptance

- [ ] A crawl at `info` produces fewer than 100 lines for a 1,000-page run.
- [ ] Every error-level line names the domain and the action to take.
- [ ] `runs.stats` is populated on completion, stop and failure alike.
- [ ] A run started with 4 GB free is refused with a clear reason.
- [ ] No log line contains HTML bodies or credentials (asserted by a test over
      a captured run).
