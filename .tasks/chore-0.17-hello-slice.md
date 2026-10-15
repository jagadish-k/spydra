# chore/0.17-hello-slice

**Task:** BUILD_PLAN 0.17 — agent-team smoke test · **Spec:** specs/010 §2 (SSE
through the edge), ADR-0012 (SSE for progress)
**ADRs that constrain this:** 0022 (the agent team — this slice EXISTS to
exercise it), 0012 (SSE)

A hello-world slice: one production line, one test, one review. The point is
to find out whether the handoff works (plan → implement → test → review →
integrate, each in a fresh context) while the stakes are trivial — not to
produce the change.

## Why this change at all

The SSE smoke route (`GET /api/crawler/__smoke/sse`, scaffold for the 0.6
edge proof, deleted by 3.6) does not send `X-Accel-Buffering: no`. Caddy's
`flush_interval -1` already handles our edge, but the header is the standard
defensive signal to ANY proxy in the path (and to future configs that miss
the flush line). One header, genuinely useful, hello-world sized.

## Files this slice owns

- backend/spydra/api/smoke.py
- backend/tests/test_smoke_sse.py
- .tasks/chore-0.17-hello-slice.md

## Acceptance (from the spec)

- [ ] The smoke SSE response declares `media_type="text/event-stream"` AND
      an `X-Accel-Buffering: no` header
- [ ] The stream emits 6 frames, one per second, each `data: {json}\n\n`
      with a `seq` field counting 0..5
- [ ] The endpoint closes cleanly after the last frame (no hang, no error)
- [ ] Tests cover the header, the content type, the frame count and the
      seq sequence — no network, no browser, no edge (unit-level against
      the app)

## Handoff log

- planner — contract above; branch opened from chore/phase-0-scaffold
  (the phase lands as one PR to develop; this slice merges back
  into the phase branch first). Files owned by this slice only.
- backend — added `X-Accel-Buffering: no` to the StreamingResponse headers
  in smoke.py. Nothing else changed (stream body, media_type,
  timing untouched). Verified: `docker compose build api` ok,
  live curl shows `x-accel-buffering: no` + `content-type:
             text/event-stream; charset=utf-8`, 6 frames seq 0..5, clean
  close (exit 0); ruff + mypy clean in the api container. For
  the test agent: the header is on the response object
  (`TestClient.get(...).headers`), frame shape is
  `data: {"seq": N, "server_ts": "..."}\n\n`, six frames at
  1s intervals — a full-stream unit test takes ~6s unless you
  inject/clock the interval or read only headers.
- test — wrote backend/tests/test_smoke_sse.py: two tests against
  `TestClient(app)` (no server). (1) header test uses a
  streamed request so content-type + X-Accel-Buffering are
  asserted from response headers without consuming the body;
  (2) frame test does one full read (~6s, real interval — no
  mocked clock, per contract) and asserts the whole body is
  exactly six `data: {json}` frames with seq 0..5 in order;
  completing the read is the clean-close proof. TEETH PROVEN:
  removed the headers argument from smoke.py → header test
  FAILED (`KeyError: 'x-accel-buffering'`), frame test still
  passed; file restored exactly (git diff shows only the
  implementer's change). Targeted run: 2 passed. Full suite
  `pytest -q`: 4 passed, 1 skipped, no regressions. Note:
  test_healthz.py already had a partial SSE test (content-type + frame count); left as-is — not this slice's file.

## Open questions

- none
