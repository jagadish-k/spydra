# feat/1.1-1.2-schema-and-domain

**Task:** BUILD_PLAN 1.1, 1.2 (+ phase-1 audit findings F1, F2, F3, F5) ·
**Spec:** specs/001-domain-model.md §1–3, §5–6; TESTING.md §1–2 ·
**ADRs that constrain this:** 0002 (postgres as queue), 0004 (stop on block —
the user-agent requirement), 0007 (append-only observations), 0008 (ports),
0010 (docker-native), 0014 (SQLAlchemy Core + Alembic), 0015 (topology),
0022 (agent team)

This is the foundation branch Phase 1 is built on. It runs alone — no lane
starts beside it (phase-1 brief: "1.1 and 1.2 on one branch, sequentially").

## Why this branch carries four things

WORKFLOW §1 says one build-plan task per branch and this carries two tasks
plus four findings. Recorded rather than hidden, as `chore/phase-0-audit`
did:

- **1.1 and 1.2 together** on the human's instruction in the phase-1 brief.
  They are the foundation every other task builds on.
- **F1, F2, F3 folded in** on the human's instruction. They are the reason
  the phase's non-negotiable tests cannot run at all, so they are not
  deferrable to a `chore/` branch that lane A would then have to wait on.
- **F5 (the user-agent)** is two lines of configuration and ADR-0004 already
  requires it. Deferring it would mean lane A writes robots.txt matching
  against a user-agent token that does not exist.

## Files this slice owns

**1.1 — schema**

- `backend/spydra/adapters/__init__.py`, `adapters/postgres/__init__.py`
  (both empty; see the note below)
- `backend/spydra/adapters/postgres/tables.py` (new — Core metadata)
- `backend/migrations/versions/*_crawl_schema.py` (new)
- `backend/migrations/env.py` (one line: `target_metadata`)
- `backend/tests/adapters/postgres/test_schema.py` (new)

**1.2 — domain and ports**

- `backend/spydra/domain/{__init__,ids,enums,entities,fetch,lifecycle,errors}.py`
- `backend/spydra/ports/{__init__,clock,frontier,fetcher}.py`
- `backend/tests/domain/{test_lifecycle,test_entities,test_state_parity}.py`

**F1–F3, F5 — the gate**

- `docker/init-schemas.sql`, `docker/crawl-bootstrap.sql` (new)
- `compose.yaml` (the test-db mount, `TEST_DATABASE_URL`, `USER_AGENT`)
- `Makefile` (`test-api` gets a database, `test-render` is added to `test`)
- `.env.example` (`USER_AGENT`)
- `backend/tests/conftest.py` (new)

**Owned by nobody else, deliberately.** `adapters/postgres/__init__.py` stays
empty and re-exports nothing. Lane A adds `frontier.py` and `domains.py`
beside it; lane C adds `observations.py`. If the package re-exported its
modules, all three lanes would have to edit one file — the conflict this
declaration exists to prevent. Import by module path.

**Not touched:** `bff/`, `frontend/`, `render/src/`, `docs/TARGETS.md` (the
human's; 1.3 is theirs), `docs/DESIGN_SYSTEM.md` (see F13), any ADR.

## Acceptance (from the spec)

Spec 001 §6:

- [ ] `make migrate` creates the full schema from empty; `make migrate-down`
      returns to empty — **on a database with nothing in it**
- [ ] Two `templates` rows with `is_active = true` for one
      `(domain_id, url_pattern)` are rejected by the partial unique index
- [ ] `page_current` returns exactly one row per page, the newest
- [ ] Every `domain_state` value in `DESIGN_SYSTEM.md` exists in the enum
      (**see F13 — one does not, and the test records the mapping instead**)
- [ ] Lifecycle transition tests cover every valid edge and reject at least
      three invalid ones
- [ ] Domain objects import nothing from `adapters/` (the stdlib-AST test
      from 0.8 activates the moment `spydra/domain/` exists)

Deferred with cause: §6's last two criteria (`field_vocabulary`,
`template_drafts`) belong to the phase-4 tables in spec 001 §4, which §1 does
not contain and 1.1 therefore does not create.

Folded-in findings:

- [ ] F1 — `make test-api` runs against a real Postgres
- [ ] F2 — `spydra_test` exists, with the same schema and grants as `spydra`
- [ ] F3 — `make test` runs the render sidecar's suite
- [ ] F5 — a descriptive user-agent with contact information is configured

## Phase 1 exit criterion (copied from BUILD_PLAN.md)

> **Exit:** one static domain **and** one JS-rendered domain crawled politely
> end to end, data in Postgres, from a YAML template. Both fetchers exercised
> by the same scheduler. The politeness tests in `TESTING.md §2` pass.
> Stopping the `render` service leaves static crawling unaffected.

Nothing on this branch satisfies any of it. This branch exists so the rest of
the phase can be written and, because of F1–F3, so that it can be *tested*.

## Sequencing decisions (planner)

- **`ports/fetcher.py` lands here, not in lane B.** 1.6 fetches `robots.txt`,
  so lane A needs the Fetcher port; defined in lane B, lane A blocks on lane
  B. It also makes the phase-1 brief's third priority achievable — if neither
  adapter authors the contract, 1.7's tests cannot need changing when 1.8
  arrives.
- **`ports/clock.py` lands here** for the same reason: ADR-0008 names it, and
  both lane A (jitter, backoff decay) and lane C (`observed_at`) take it.
- **Core table metadata is the schema's single description.** `env.py` already
  reserves `target_metadata` for 1.1 and the Makefile documents
  `make revision` as autogenerate, so the alternative is a hand-written
  migration and an autogenerate target that silently emits empty revisions.
  `tables.py` is the source; the migration is written from it and committed.
  Judged to be inside ADR-0014's envelope rather than a new decision —
  **say if you want it recorded as an ADR.**
- **`spydra_test` is bootstrapped from the same SQL as `spydra`.** The grant
  boundary is the thing spec 010 §6 proves; a test database with hand-copied
  grants would drift from the one `make verify-grants` checks, and the drift
  would surface as a passing test on a boundary that had moved.
  `docker/init-schemas.sql` keeps its path and its mount so BUILD_PLAN 0.7's
  proof is untouched; the per-database half moves into
  `docker/crawl-bootstrap.sql` and is included twice.
- **The lifecycle is modelled as (state, event) → state**, not as a set of
  legal state pairs. `active → paused` by operator and `active → paused` by
  three 403s are the same edge but not the same event, and the run report has
  to tell them apart later. The event is also the thing the caller actually
  has.

## Open questions

- **1.3 is unresolved and this branch does not touch it.** `docs/TARGETS.md`
  exists as an empty untracked file in the working tree. It is the human's
  (phase-1 brief: "do not write TARGETS.md"). 1.4 and all of lane C's
  fixtures wait on it.
- ~~**F4 — the claim query**~~ — **settled by the human: lock the domains
  row.** ADR-0026 written first (rule 1), then spec 002 §1, §3 and §9
  corrected to match. Both queries were then raced against real Postgres on
  two connections: the original claimed twice in **20 rounds out of 20**, the
  ADR's in 0. One claim in the planning note was **wrong** and is corrected
  in the ADR — Postgres does *not* reject `FOR UPDATE` on a `WITH`
  reference; it accepts the statement and quietly locks only `crawl_queue`,
  which is worse, because an error would at least have been visible. Lane A
  implements it in 1.5; the committed two-worker test is 1.5's, not this
  slice's.
- **F13 (new, found writing the parity test)** — `DESIGN_SYSTEM.md`'s
  lifecycle-colour table lists `pending`; the enum has `awaiting_approval`.
  Spec 001 §6 asserts every documented state exists in the enum, and one does
  not. The two readings are a display label (`pending` renders
  `awaiting_approval`, which its own "Awaiting your approval" meaning
  supports) or a genuine naming disagreement. `DESIGN_SYSTEM.md` is not a
  state authority — ADR-0025 gave that to `UI_STATES.md` — so the likely fix
  is a one-word docs correction, which is outside this slice's file set.
  `test_state_parity.py` carries the mapping explicitly and fails if a
  seventh row appears. **Your call.**
- **The gate has not been run.** See the handoff log.

## Handoff log

- planner — read AGENTS.md, WORKFLOW, BUILD_PLAN §1, specs 001/002/003/012,
  TESTING §1–2, ADRs 0002/0003/0004/0007/0008/0016/0022 and
  `.tasks/chore-phase-0-audit.md`. The lane plan for the phase was agreed with
  the human before this branch opened; `ports/` moved into this slice and
  `adapters/postgres/observations.py` was assigned to lane C as part of that.
  Thirteen findings filed; F1, F2, F3, F5 folded in here on instruction, F4
  and F13 left open above.
- backend — 1.1 and 1.2 landed, plus F1/F2/F3/F5.
  - `tables.py` is the schema's single description; the migration's twelve
    `op.create_table` blocks were **rendered mechanically from it**
    (`alembic.autogenerate.render_python_code` over `CreateTableOp.from_table`)
    rather than transcribed. That caught two things a hand copy would not:
    `sa.true()` renders as `server_default=sa.text('1')`, and `DEFAULT 1` on a
    `boolean` column is a hard error in Postgres; and the renderer emits bare
    `Text()` inside `postgresql.ARRAY(...)`. Both fixed in both files.
  - The migration drops the two enum types explicitly. `op.drop_table` does
    not, and an un-dropped type makes the *second* `upgrade head` after a
    `downgrade base` fail on "type already exists" — which is exactly the
    cycle `check.yml` runs since the phase-0 audit's F4.
  - `env.py` gained an `include_object` filter. `page_current` is a view, so
    it is absent from the metadata, and reflection hands autogenerate
    something that looks like an unknown table — whose next move is to
    propose dropping it, in a revision someone would then run.
  - `Backpressure` is on the Fetcher contract in `domain/errors.py`, not in
    the render adapter. 1.7's tests should not change when 1.8 lands, and
    they cannot if the first adapter written is also what names the 503 case.
  - A socket-level "no outbound network" guard was written for `conftest.py`
    and then **removed**: the version that worked blocked asyncpg's own
    connection, and a version permissive enough not to would have had to
    guess at what respx and the fake render service do to the socket layer.
    It is a cheap addition for a slice that can run the suite and prove it
    does not fight lane B. Filed rather than shipped unproven.
- test — 61 tests, 1 skipped (the baseline's empty downgrade), 10 integration
  tests deselected for want of a database. Written from spec 001 §2's diagram
  and §6's criteria, not from `lifecycle.py`.
- reviewer — **not run.** Per ADR-0022 §4 this must be an agent that did not
  write the code, and the roles were not available as spawnable subagents
  here — the same deviation `chore/phase-0-audit` recorded. The diff is the
  thing to hand it.
- backend (second pass) — **`make migrate` failed on the human's machine**:
  `column "is_active" is of type boolean but default expression is of type
  integer`. Same defect class as the `respect_robots` one caught during
  rendering, and the reason the first pass missed it is worth keeping: the
  DDL check that was run compiled `tables.py` **directly**, where
  `sa.false()` renders correctly as `DEFAULT false`. The corruption happens
  in the *render* step on the way into the migration, so checking the
  metadata could never have found it. Fixed in both files, and
  `sa.true()`/`sa.false()` are now spelled `sa.text("true")`/`sa.text("false")`
  in `tables.py` so the trap is gone at the source rather than patched
  downstream. `test_migrations.py` gained a static guard for the class.
- integrator (second pass) — **the containerised gate still has not run**,
  but a throwaway PostgreSQL 16.15 cluster was available in the cloud
  sandbox, so most of what was unproven is now proven against a real
  database — outside this repository and outside the development machine,
  nothing installed on the host:

  | Proof | Result |
  | --- | --- |
  | `init-schemas.sql` + `init-test-db.sql` on a fresh cluster | `crawl` and the three roles in **both** `spydra` and `spydra_test`; the `\i` include ran twice as intended (F2) |
  | `alembic upgrade head` | 12 tables, 1 view, 2 enum types, 4 partial indexes |
  | `downgrade base` | leaves only `alembic_version`; **0 enum types** — the explicit DROP TYPE works |
  | `upgrade head` a second time | clean, which is the cycle an un-dropped type would have failed |
  | column defaults | `is_active = false`, `respect_robots = true` |
  | full `pytest`, integration included | **73 passed, 1 skipped** |
  | the claim query, two connections, 20 rounds each | original 20/20 wrong, ADR-0026 0/20 |

  One real test defect surfaced that no static check would have: the
  `page_current` test bound `observed_at` as a string, and asyncpg binds by
  type and refuses to parse a timestamptz out of text. Fixed to `datetime`
  and `Decimal`.

  **Still unproven, and still needs the development machine:** Postgres 18
  rather than 16; Python 3.15 rather than 3.13; `make test-render`;
  `make verify-grants` after its SQL moved file; `make reset && make up`,
  which is the only thing that exercises the initdb mounts as compose wires
  them; and `make check` whole, with the pre-commit hook, against the
  versions the lockfile pins.

- backend (third pass) — **`make test-api` errored on all ten integration
  tests, and the cause was mine.** The signal was at the bottom of the run,
  not the top: `PytestConfigWarning: Unknown config option: asyncio_mode`.
  pytest-asyncio was added to `pyproject.toml` and **`backend/uv.lock` was
  not re-resolved**, so `docker/api.Dockerfile`'s `uv sync --frozen` had
  never installed it; without the plugin every async fixture is unhandled and
  the ten `engine`-dependent tests error at setup. The
  `pytest_fixture_post_finalizer` assertions underneath are downstream noise
  from the same single cause.

  Two things follow:

  1. `uv.lock` re-resolved with **uv 0.13.1**, the version
     `api.Dockerfile` pins and the version that wrote the existing lock, and
     against a real CPython 3.15.0 — not with whatever uv was to hand, since
     the lock records which uv produced it. The diff is one package:
     `pytest-asyncio 1.4.0`. `version`/`revision` unchanged at 1/5. The suite
     was then re-run against exactly that pin: **73 passed, 1 skipped.**
  2. **`make lock` added**, because this will recur. `uv sync --frozen`
     failing on a stale lock is correct behaviour — it is what stops a
     dependency reaching an image unlocked — but it makes adding a dependency
     a two-step operation with no sanctioned second step, and the failure
     surfaces as ten unrelated-looking fixture errors rather than as "the
     lock is stale". Every lane that adds a dependency would have found this
     the same way.

  Not done, and outside this slice's file set: `make lock` is absent from
  `AGENTS.md` § Commands and from `DEVELOPMENT.md` § Commands, which
  BUILD_PLAN 0.2 makes the Makefile's mirror. **Two one-line additions for
  you, or say the word and I will take them.**

- ops (F14, new) — **`make reset-deps` has never worked**, and that is the
  whole reason the pytest-asyncio failure survived three rounds:

  ```make
  $(COMPOSE) stop && docker volume rm -f spydra_venv ... || true
  ```

  `stop` stops containers; it does not remove them, and a **stopped**
  container still holds a reference to its volumes, so `docker volume rm`
  fails with "volume is in use". `|| true` then swallowed that, so the target
  printed nothing, exited 0 and did nothing. The venv volume therefore
  survived a lockfile change, an image rebuild and three runs of the target
  that exists to drop it — while `make up --build` dutifully rebuilt an image
  whose `/app/.venv` was shadowed by the old volume every time.

  Proof it was not the lock or the Dockerfile: `uv sync --frozen` was run
  against the committed `pyproject.toml` + `uv.lock` with the pinned uv
  0.13.1, and it installs `pytest-asyncio==1.4.0`. The build step was correct
  throughout.

  Fixed: `down` instead of `stop`, and the `|| true` removed —
  `volume rm -f` is already a no-op for a volume that does not exist, so the
  only thing that guard could hide was a real failure. The target now says
  what it dropped.

  **This is a phase-0 defect** (BUILD_PLAN 0.2's Makefile), folded into this
  branch rather than split to a `fix/` branch because F1's acceptance —
  `make test-api` running against a real Postgres — is unreachable while the
  venv cannot be refreshed. Declared rather than hidden; say the word and I
  will split it. It is also a defect the phase-0 audit could not have caught:
  its harness had no Docker, which is the same reason it took three rounds
  here.

- ops (F15 + the sweep, on the human's instruction to stop costing rounds) —
  swept the Makefile for the F14 class: **a target that reports success while
  doing nothing.** Three more found.

  **F15 · `make verify-grants` could not fail, and after 1.1 it was aimed at a
  real table.** This is the proof spec 010 §6 and BUILD_PLAN 0.7 both rest
  on — the only thing standing between two schemas and a distributed
  monolith — and it printed "✓ grants hold" while proving nothing:

  - Its throwaway table was **`crawl.runs`**. Free before 1.1; after 1.1 that
    is the run history, and the target's last act is `DROP TABLE crawl.runs`.
    It survives today only because page_observations, crawl_queue and
    asset_queue hold foreign keys into it — luck, not design.
  - **No psql call carried `-v ON_ERROR_STOP=1`** (grep: zero occurrences in
    the whole file), and psql exits 0 on a failed statement by default. Every
    assertion in the target was therefore incapable of failing, including the
    CREATE that was silently doing nothing.
  - The rejection check was `grep -q "permission denied" && echo ✓` followed
    by `;`, so an INSERT that failed for any other reason — no connection,
    wrong table — passed.
  - The recipe's exit status was the final `DROP`'s, not the assertions'.

  Rewritten: a probe table that cannot collide (`crawl.__grant_probe`),
  `set -e`, `ON_ERROR_STOP=1` on every connection, the specific error demanded
  rather than any failure accepted, and cleanup on every exit path via `trap`.

  **Also fixed:** `fmt-staged` ended on `[ -n "$files" ] && ...`, so it
  exited 1 — failing the pre-commit hook — whenever nothing matched;
  `typecheck-changed-py` would have called `mypy` with no arguments in the
  same case. And while rewriting `verify-grants` I put its
  `skip_if_missing` guard on its own recipe line, where `exit 0` ends only
  that line's shell and make runs the body anyway. Caught by the new test,
  not by reading.

  **`backend/tests/test_makefile_guards.py` — the class is now gated.** Seven
  checks, in `make check` by way of `make test-api`, stdlib only, following
  task 0.8's precedent of a pytest over a lint because it blocks CI where a
  lint warns: every guarded path exists or is declared pending; the pending
  list only shrinks; no guard sits alone on its line; no docker command's
  result is swallowed; volumes are never removed after a mere `stop`; every
  psql assertion stops on error; the grant probe never names a real table.

  **The tests were then verified by mutation** — each defect re-introduced
  one at a time, nine in all, to check the guard actually fires. Worth
  recording that **two of the first five were decoration**: both matched on
  physical lines, and the Makefile's shell functions wrap, so `psql` sat on
  one line and its connection URL on the next. A third was too broad and
  flagged a legitimate best-effort cleanup. The unit is now the shell
  command — logical lines split on `;` — and all nine mutations are caught
  while the real Makefile is clean. A guard test nobody tried to break is
  itself the F14 pattern.

  Verified: ruff clean, mypy --strict clean over 26 files, **80 passed, 1
  skipped** against real Postgres.

- integrator (first pass) — **the gate had NOT been run. This environment has no Docker.**
  It is a Linux VM with the repository mounted, the same limitation
  `chore/phase-0-audit` recorded under Deviations, and its Python is 3.10
  where the project pins 3.15. `make check`, `make migrate` and
  `make migrate-down` are all containerised (ADR-0010, AGENTS.md rule 1) and
  cannot run from here.

  **What was proven, and how.** Rather than claim the code is fine, the
  Python half was verified in an isolated throwaway environment outside this
  repository and outside the development machine — nothing installed on the
  host, nothing added to the repo, rule 1 untouched:

  | Check | Result |
  | --- | --- |
  | `ruff check` (the repo's own config) | clean |
  | `ruff format --check` | clean |
  | `mypy --strict` over `spydra`, `migrations`, `tests` | clean, 25 files |
  | `pytest -m "not integration"` | 61 passed, 1 skipped |
  | `tables.py` → Postgres DDL, compiled and read | all 12 tables, 2 enums |

  **What remains unproven and needs the development machine**, in the order
  it will fail if something is wrong:

  1. `make migrate` then `make migrate-down` then `make migrate` again, on an
     empty database. The enum drops and the view drop are the parts most
     likely to be wrong, and only the second upgrade exercises them.
  2. `make reset && make up` — F2 changed `docker/init-schemas.sql`, and
     initdb scripts run **only on a fresh `pgdata` volume**, so the test
     database does not appear on an existing one. `\i /bootstrap/...` and the
     `20-` ordering are both unexercised until that happens.
  3. `make test-api` — the ten integration tests, and whether dropping
     `--no-deps` behaves (compose should start `db` via `api`'s `depends_on`).
  4. `make test-render` — new target, never run.
  5. `make verify-grants` — unchanged in intent, but its SQL moved file, so
     BUILD_PLAN 0.7's proof needs re-running rather than assuming.
  6. `make check` whole, and the pre-commit hook, which runs ruff and mypy in
     the container against the versions the lockfile actually pins.

  Verified on 3.13 is not verified on 3.15, and a mounted repo is not the
  stack. Stated rather than approximated, per AGENTS.md § When you are stuck.

  **`--no-verify` was used on this commit, and is declared here** per
  WORKFLOW §2. The pre-commit hook runs `ruff` and `mypy` through the
  container; with no Docker it cannot run at all, so bypassing it was the
  only way to produce a commit. The checks it would have run were run — see
  the table above — against a different interpreter. The hook is not
  satisfied and the commit should be treated as ungated until it is.

  **`BUILD_PLAN.md` is deliberately NOT ticked.** 1.1 and 1.2 are written,
  not done: AGENTS.md says the box is ticked when the definition of done
  holds, and `make check` has not passed. Ticking them now is the exact
  thing BUILD_PLAN § How to use this warns against. Tick them in the PR,
  after the gate.
