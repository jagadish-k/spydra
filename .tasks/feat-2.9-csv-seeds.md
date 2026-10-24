# feat/2.9-csv-seeds

**Task:** BUILD_PLAN 2.9 — "CSV seed parsing with per-row validation and no
HTTP. Rejects report the row and the reason. Done when: a file with one bad
row imports the rest and names the failure, and nothing in the parser can
make a network call." · **Spec:** 004 **§6 (new — this slice writes it;
BUILD_PLAN's pointer said §4, which is the dry-run, 2.10's. Fixed in this
slice.)** · **ADRs that constrain this:** 0004 (politeness is per host — the
seed/host check), 0006 (templates versioned; a CSV carries none, ever),
0027 (nothing here reintroduces `required` — a CSV has no extraction rules
to carry it), 0030 (a template-less page is `no_template`, not evidence
against the domain — verified below, no change needed)
**Stacked on:** `feat/2.8-run-events` (PR pending)

## Decided (user)

- **The CSV is minimal** — columns `host,seed_url`, plus optional
  `render_mode` and `crawl_delay_ms` with defaults. Templates still come
  from YAML today, UI later. CSV is for onboarding many seeds fast.

## Decided (planner)

Verified on `feat/2.8-run-events` @ `53b05db` (clean tree; four untracked
`pr-*-body.md`, no slice in flight).

### 0. What this slice is, and shares with 1.14

CSV seed loading is **scaffolding with the same end date as the YAML
loader**: `3.2` deletes `spydra/load.py` and deletes these two modules with
it (BUILD_PLAN 3.2 "Delete the YAML loader from 1.14" — the CSV loader dies
in the same stroke; say so in both module docstrings). No schema, no
validator framework, no format anyone could grow attached to. It exists so
an operator can onboard many seed URLs fast while templates still come from
YAML.

### 1. The format (spec 004 §6, written by this slice)

- **Header row required, exact and ordered.** The first record must be
  literally one of, lowercase, no extra columns:

  ```
  host,seed_url
  host,seed_url,render_mode
  host,seed_url,render_mode,crawl_delay_ms
  ```

  A wrong or missing header **refuses the whole file** (`refused: header
must be host,seed_url[,render_mode[,crawl_delay_ms]] — got: …`). Rationale:
  the header is the column contract; inferring it means a missing header
  turns row 1's data into column names and every reject message becomes
  unnameable. Explicit beats convenient for a file the operator will fix
  by hand.

- **Quoting/escaping: stdlib `csv` defaults** (comma, `QUOTE_MINIMAL`,
  UTF-8). No new dependency — ruamel is for YAML.
- **Fields are stripped** of surrounding whitespace before validation
  (the one hand-edited-CSV forgiveness; `host, https://…` after a comma is
  padding, not content).
- **Blank lines are skipped silently.** No comment syntax — inventing one
  is format growth.
- **Optional columns' defaults match `load.py`'s `_domain` and
  `_INSERT_DOMAIN` exactly:** `render_mode` default `static`
  (`RenderMode.STATIC`), `crawl_delay_ms` default `2000`. `respect_robots`
  is **not a column** — fixed `true`, the `_domain` default. Naming it a
  column is scope the user did not decide.
- **`seed_url` must be an absolute http/https URL.** `host` stays a column
  (the user's decision) and is cross-checked: the URL's netloc must equal
  it case-insensitively, port included — the same comparison `_seed` makes.
  A path-only seed is a `bad_url` reject telling the operator to write the
  full URL, not a guess against a default scheme.
- **Duplicate rows:** an exact duplicate `(host, seed_url)` is
  **deduplicated silently, not a reject** — `_ENQUEUE`'s
  `ON CONFLICT (run_id, url_hash) DO NOTHING` makes the two outcomes
  byte-identical in the database, so reporting one would be reporting a
  non-failure. But the same host with a **different** `render_mode` or
  `crawl_delay_ms` than an earlier accepted row is a `conflict` reject on
  the later row: a domain has one setting, and picking one silently is the
  guess this loader refuses to make.

### 2. Reject vocabulary (row numbers are file line numbers)

Rejects name the **file line number** (`csv.reader.line_num` — what the
operator's editor shows; header is line 1, first data row line 2). No
arithmetic. In `load.py`'s refusal style — name the thing, say why it
matters, say what to do:

| Token             | When                                                                                                                                                                               |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `empty_host`      | host blank after strip                                                                                                                                                             |
| `empty_seed`      | seed_url blank after strip                                                                                                                                                         |
| `bad_url`         | `urlsplit` yields no scheme or no netloc (includes path-only)                                                                                                                      |
| `off_scheme`      | scheme not http/https (`mailto:`, `javascript:`, …) — spec 004 §1 rule 2                                                                                                           |
| `host_mismatch`   | netloc ≠ host (case-insensitive). Message reuses `_seed`'s reasoning: "each seed is crawled under its domain's robots.txt and politeness, so it belongs under the domain it is on" |
| `bad_render_mode` | not exactly `static`, `rendered` or `auto` (message names the three)                                                                                                               |
| `bad_delay`       | crawl_delay_ms not a whole number ≥ 0 (matches the `configured_crawl_delay_ms_non_negative` CHECK; negative is a row reject here, not a transaction failure later)                 |
| `column_count`    | wrong field count for the header ("expected 2, got 5")                                                                                                                             |
| `conflict`        | same host, different render_mode/crawl_delay_ms than an earlier accepted row; names both values and the earlier line                                                               |

File-level refusals (nothing written, `refused:` prefix, exit 1): bad
header; header only (no data rows); **every** data row rejected (no empty
run is started).

### 3. Partial import — parse is per-row, the transaction stays atomic

**Valid rows load, invalid rows are reported, nothing about a bad row aborts
the file.** Defence, in the spec section too: CSV is row-oriented bulk
onboarding — one typo in row 40 of 200 should not cost the file, and unlike
YAML the rows share no structure (a YAML file is one coherent template set;
a CSV file is 200 independent facts). **The database transaction is still
all-or-nothing** (configuration.py's one-transaction guarantee is
load-bearing and untouched): parse-level rejects are removed before `apply`
runs.

One carry-over from the YAML loader, kept as-is and documented: a domain
that already exists in a state a file cannot approve (`paused`, `broken`,
`archived`) makes `apply` raise `RefusedConfiguration` and roll back the
**whole file**. That is a conflict with the world, not with the row's
syntax; the operator removes that host's rows and re-runs. Deliberate:
pre-checking states outside the adapter would fork `_APPROVAL_PATH`.

**Exit codes:** `0` only when every data row imported (silent dedupes don't
count against it). `1` when any row was rejected (the valid rows **still
imported** — the summary says exactly what happened; an exit code is the
only channel `make` has and "imported with rejections" is not "success") or
any refusal (nothing written). Rejects print to stderr one per line;
stdout carries the success line, `run N started from <path>` like the YAML
CLI.

### 4. The apply path — no production change to `configuration.py`

Verified by reading, not hoped: `PostgresConfiguration.apply` loops
`domain.template_rows()` — `templates=()` skips the loop, inserts/updates
the domain, starts the run, enqueues seeds. **A `DomainConfig` carries
seeds with no templates today.** And the crawl of a template-less domain is
already honest everywhere it matters:

- `scheduler/crawl.py`: `matching(...)` returns `None` → the page is
  fetched under full robots/politeness, the **structured (JSON-LD) rung
  runs without a template** (1.10 built it so), an observation is written;
- `observations/writer.py` `_reason`: every 200 lands in `unknown_pages`
  as `no_template` — the operator is told exactly what is missing;
- `_apply_health` is skipped (`_extracted(None)` is false — the 1.11
  review fix): **the domain is never moved to `broken`/`awaiting_approval`
  by its template-less pages**;
- `_discover` returns immediately on `template is None`: **no discovery
  expansion — the run crawls exactly the file's seeds and drains.**

So a CSV file produces: domains `active` (via `_APPROVAL_PATH` —
`discovered`/`awaiting_approval` walk PROPOSE/APPROVE; **`active` re-seeds
into the new run**, render settings and delay floor updated), one run per
file (YAML precedent), seeds enqueued at depth 0, and an inbox that says
"give these domains templates". That is the product: onboarding many seeds
fast, templates later from YAML or the UI. **No variant of `apply` is
built.**

### 5. Parser purity — the two-module split

- `backend/spydra/seed_csv.py` — **the parser**, pure:
  `parse(text) -> SeedFile` (`SeedFile.domains: tuple[DomainConfig, …]`,
  `SeedFile.rejects: tuple[Reject, …]`; `Reject` carries `line`, `token`,
  `detail`). Imports allowlisted to: `csv`, `dataclasses`, `typing`,
  `urllib.parse`, `spydra.domain.enums` (RenderMode), and `spydra.load`
  (for `DomainConfig` — the one configuration carrier both loaders feed to
  `apply`; a second shape would fork the apply contract, and the dependency
  dies with both modules in 3.2). **No DNS, no `getaddrinfo` — host
  validation is syntax-only**, stated in the module docstring.
- `backend/spydra/load_seeds.py` — `async load(configuration, text)` +
  the CLI (`python -m spydra.load_seeds <file.csv>`), report printing,
  exit codes.

Proof, both halves:

1. **Import allowlist test** (the `discovery/test_links.py` idiom,
   strengthened from a denylist to an allowlist): AST-walk
   `seed_csv.py`'s imports and assert every one is on the list above.
   Input-unbounded — a future `httpx` cannot drift in.
2. **Socket-block runtime test**: monkeypatch `socket.socket` and
   `socket.getaddrinfo` to raise, then `parse()` a file full of
   real-looking hosts (`example.com`, `halden.fixtures:8099`, an IP). If
   any path dials, the test fails. Proves the execution, not just the
   imports.

### 6. Make target, spec, BUILD_PLAN

- `make load-seeds f=seeds.csv` — mirrors `load` exactly (same guard,
  same `$(COMPOSE) run --rm api`, path relative to `backend/`).
- **Spec 004 gains §6 "CSV seed files" after §5**, carrying the format,
  the reject vocabulary, the partial-import rule and its defence, and the
  template-less-crawl semantics above. §6 and not §4a: the CSV section is
  a new topic, not a dry-run appendix (the §3a precedent was an
  elaboration of §3); **no existing section is renumbered** — §4/§5
  cross-references elsewhere hold. §5's list stays discovery-scoped; §6
  carries its own criteria.
- **BUILD_PLAN 2.9's pointer fixed in this slice** to `(spec 004 §6)` —
  one line. The task is **not** ticked.
- **No ADR.** No structural decision: no new runtime dependency (stdlib
  `csv`), the database semantics are unchanged, and partial-vs-atomic is
  a parse-level UX choice on a scaffold with a deletion date. If the human
  reads the partial-import stance as structural, it is 0043 — planner's
  call is that it is not, because the property ADRs protect (the atomic
  transaction) is untouched.

## Files this slice owns

- `backend/spydra/seed_csv.py` (new — the pure parser)
- `backend/spydra/load_seeds.py` (new — loader + CLI)
- `backend/tests/test_seed_csv.py` (new — parser, reject vocabulary,
  allowlist import test, socket-block test)
- `backend/tests/adapters/postgres/test_load_seeds.py` (new — one run per
  file; re-seed of an existing `active` domain; template-less `DomainConfig`
  through the real `apply`)
- `backend/tests/fixtures/phase2/seeds.csv` (new — hand-written, against
  `halden.fixtures:8099`, and **is itself the one-bad-row file**: one
  `host_mismatch` row among valid ones)
- `Makefile` (one target: `load-seeds`, after `load`)
- `docs/specs/004-discovery.md` (new §6 only)
- `docs/BUILD_PLAN.md` (the 2.9 pointer line only — not the checkbox)

Explicitly not owned / not touched: `backend/spydra/load.py`,
`backend/spydra/adapters/postgres/configuration.py`,
`scheduler/crawl.py`, `observations/writer.py` — verified sufficient as
read, §4 above. A change to any of them in this slice is a defect, not a
feature.

## Acceptance (from BUILD_PLAN 2.9's done-when)

- [x] A file with one bad row imports the rest and names the failure —
      row (file line number) and reason, in the loader's refusal style;
      the bad row aborts nothing.
- [x] Nothing in the parser can make a network call — proven by the
      import-allowlist AST test and the socket-block runtime test; host
      validation is syntax-only (no `getaddrinfo`), stated in the module.
- [x] Header, duplicate and optional-column behaviours are pinned by
      tests: exact ordered header (three spellings) refuses the file when
      wrong; exact duplicates dedupe silently; same-host setting
      conflicts reject the later row; defaults are `static`/`2000`;
      `respect_robots` is fixed true.
- [ ] A real CSV through `make load-seeds` seeds domains and starts a run
      against Halden — fixture host `halden.fixtures:8099` (compose
      `phase1-exit` profile; loopback, no real network). Demonstrated
      manually from the task file's commands and recorded in the handoff
      log; not scripted as a new target (2.9 is not a phase exit —
      `phase1-exit.sh` already exists for that shape). **Commands pinned
      in the handoff log (spydra-test entry); the E2E crawl semantics
      themselves are pinned by a real-worker test against the in-process
      fixture site.**
- [x] Spec 004 §6 exists; BUILD_PLAN 2.9's pointer names it.
- [ ] `make check` green.

## Handoff log

- planner — contract above. Key verification: `apply` already carries
  template-less `DomainConfig`s, and the template-less crawl is honest
  (JSON-LD rung runs, `no_template` inbox, no health verdict, no
  discovery) — zero production change outside the two new modules, the
  Makefile and the two docs. Spec gap closed as new §6; BUILD_PLAN
  pointer fixed. No ADR (§6 of Decided). Open questions: two, below.
- backend (2.9) — both modules, Makefile target, spec 004 §6 written;
  tests and the `seeds.csv` fixture left to spydra-test (production-only
  mandate). Decisions a reader cannot recover from the diff:
  - **`off_scheme` before `bad_url`'s netloc check.** `mailto:` has a
    scheme and no netloc; checking netloc first reported it `bad_url`.
    Smoke-tested, found wrong, reordered — the pinned table names
    mailto/javascript as `off_scheme`.
  - **Header refusal is a `ValueError` from `parse`.** The import
    allowlist cannot reach `spydra.domain.errors`, so the parser raises
    stdlib `ValueError` and the CLI's `__main__` prints it with the
    `refused:` prefix exactly as `load.py` prints `RefusedConfiguration`.
  - **`load` returns `ImportResult(run_id | None, seed_file)` instead of
    raising on empty files.** On every-row-rejected the operator must
    still see the reject lines, which an exception from inside `load`
    would strand; `run_id is None` means nothing was written and the CLI
    composes the refusal (header-only vs all-rejected) from the rejects.
    World-conflict `RefusedConfiguration` still propagates from `apply`
    and rolls back the whole file.
  - **Delay parsing is `isascii() and isdigit()`**, not `int()`: `int()`
    accepts `"5_000"` (50) and `"+5"`, and a politeness floor the operator
    did not write is the one mistake this loader refuses to make
    silently. Negative and non-numeric are `bad_delay`.
  - **An empty cell in a declared optional column is a reject**
    (`bad_render_mode`/`bad_delay`), not the column default: defaults
    belong to absent columns, which only the header can make absent.
  - **Header match is case-sensitive and stripped** — "literally one of,
    lowercase" pinned case; strip is the one hand-edited forgiveness and
    applies to header fields as fields.
    Verified: `make lint` (ruff + mypy --strict + eslint + prettier) clean;
    `make test-api` 1187 passed, 2 skipped (parent-branch count; nothing
    moved — `configuration.py` untouched). Parser semantics smoke-tested in
    the api container against every token, the three header spellings,
    dedupe, conflict, defaults and case-insensitive host compare (port
    included). BUILD_PLAN pointer confirmed already fixed by the planner in
    f6b8f42 — not redone. `make load-seeds` demo against Halden still to be
    run (needs `phase1-exit` profile up; recorded here when done or handed
    to integrator).
- spydra-test (2.9) — tests and the fixture, from the acceptance criteria
  and §1–§5 (not from the implementation). Files:
  `backend/tests/test_seed_csv.py` (49 tests), `backend/tests/adapters/
postgres/test_load_seeds.py` (16), `backend/tests/fixtures/phase2/
seeds.csv` (the committed one-bad-row file: two Halden seeds + a line-4
  `host_mismatch`; pinned by a parser test so it cannot drift). Suite:
  `make test-api` **1252 passed, 2 skipped** (parent 1187+2; +65).
  `make lint` clean (ruff, mypy --strict, eslint, prettier). Coverage of
  the boxes: done-when at all three levels (parse, DB row counts, CLI);
  every reject token on a crafted row incl. the backend's two finds
  (`mailto:` → `off_scheme`, `5_000` → `bad_delay`); the three header
  spellings + six refusals (order/name/invented column/extra/uppercase/
  missing); defaults asserted on the `DomainConfig`; empty-cell-in-declared
  -column → reject; dedupe silent; conflict names the earlier line; case-
  insensitive host compare with port both ways; world-conflict refusal for
  paused/broken/archived mirrors the YAML suite; exit contract through the
  real CLI subprocess (0 good / 1 partial with stdout summary + stderr
  rejects / 1 refusals with nothing written). **E2E template-less crawl**:
  a CSV seed on the in-process `FixtureSite` host → `load_seeds.load` →
  the real `python -m spydra.worker` subprocess → run completes, exactly
  one queue row `done` (the seed page links the whole catalogue — proof
  discovery never expanded), `unknown_pages` = `(canonical_url(seed),
"no_template")`, one 200 observation, domain stays `active`, the site
  saw one page request. Purity proven twice: AST **allowlist** (not
  denylist) over `seed_csv.py`'s imports, and a runtime parse with
  `socket.socket`/`getaddrinfo` raising. **Mutations, each red then
  restored then green** (production verified byte-clean after:
  `git diff backend/spydra/` empty): ① `line_num - 1` → 22 red (reject
  numbering); ② netloc-before-scheme → 3 red (mailto/javascript/
  protocol-relative misreported); ③ dedupe `seen` check dropped → 1 red;
  ④ conflict branch removed → 2 red; ⑤ header compare sorted → 1 red
  (wrong-order accepted); ⑥ `isascii/isdigit` → `int()` → 3 red (`5_000`,
  `-5`, `+5` import); ⑦ partial-import `sys.exit(1)` dropped → 1 red (CLI
  exit 0 on rejects); ⑧ empty-domains guard removed → 4 red (empty run
  started on all-rejected/header-only). Defects: **none genuine** — three
  authoring bugs in my own tests (rows not matching their header's field
  count; unpacking `SeedFile` instead of `.domains`) found by the suite
  and fixed before first green. `make check` left to the integrator (lint
  - test-api green here; no API change so `make types` cannot drift —
    verified no backend source touched). **Halden demo commands pinned**
    (not run — needs the phase1-exit profile; integrator or human):
  ```sh
  docker compose --profile phase1-exit up -d db fixtures
  make migrate
  make load-seeds f=tests/fixtures/phase2/seeds.csv
  # expect exit 1: stderr "line 4: host_mismatch — …", stdout
  # "1 domain, 2 seeds imported" + "run N started from …"
  docker compose up -d worker && docker compose logs -f worker
  # run completes; crawl_queue rows for the run → done (exactly the two
  # seeds); unknown_pages → 2 × no_template; domains.state stays active
  docker compose --profile phase1-exit rm -sf fixtures
  ```

## Open questions

- **File-level refusal on a paused/broken domain** (§3): kept from the
  YAML loader deliberately. If bulk onboarding in practice hits paused
  domains often enough to annoy, the fix is per-host reporting inside
  `apply` — a change to `configuration.py` this slice does not make. Flag
  to the human if it bites.
- **`spydra.load` in the parser's allowlist** (§5): the dependency is one
  dataclass and dies with both modules in 3.2. If the reviewer prefers
  `DomainConfig` lifted to a pure home (e.g. `spydra/domain/`), that is a
  small refactor of 1.14's exports — deferred, not decided, because
  moving it touches three files to save one import.
