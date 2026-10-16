#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Phase 0 audit — re-runs the proof each BUILD_PLAN task names, and reports
# PROVEN / UNPROVEN / BROKEN from what came back, not from the tick.
#
#   bash scripts/audit-phase0.sh                 # everything (~25-40 min)
#   bash scripts/audit-phase0.sh 0.6 0.7 0.13    # only those sections
#   bash scripts/audit-phase0.sh gate            # only the hook/gate checks
#
# Writes a transcript to .audit/phase0-<timestamp>.log and a verdict table to
# .audit/verdicts.tsv. Both are untracked scratch (add .audit/ to .gitignore
# or delete it afterwards).
#
# SAFETY
#   - Every mutation is reverted in a trap, including on Ctrl-C.
#   - It never touches `origin`. Push tests use a throwaway bare remote.
#   - `make reset` DROPS the dev database volume. Sections 0.7, 0.10 and 0.13
#     need that (the ticks claim a fresh-volume proof). Set KEEP_DB=1 to skip
#     the destructive sections instead.
# ---------------------------------------------------------------------------
set -uo pipefail

cd "$(dirname "$0")/.."
REPO=$(pwd)
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p .audit
LOG="$REPO/.audit/phase0-$STAMP.log"
TSV="$REPO/.audit/verdicts.tsv"
: >"$TSV"

KEEP_DB=${KEEP_DB:-0}
WANT=("$@")

B=$'\033[1m'; R=$'\033[0;31m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; O=$'\033[0m'

# --- plumbing ---------------------------------------------------------------

log()  { printf '%s\n' "$*" | tee -a "$LOG"; }
head2() { log ""; log "${B}=== $* ===${O}"; }

# run CMD, echo it, STREAM its output (a silent `make check` looks like a
# hang for minutes), capture the same bytes into $OUT, return its exit status.
OUT=""
run() {
  log "\$ $*"
  local tmp; tmp=$(mktemp)
  eval "$@" 2>&1 | tee -a "$LOG" | sed 's/^/    /' | tee "$tmp"
  local rc=${PIPESTATUS[0]}
  OUT=$(sed 's/^    //' "$tmp"); rm -f "$tmp"
  return "$rc"
}

# Say how long a slow step takes before starting it, so a long wait is
# expected rather than alarming.
slow() { log "${Y}·${O} this takes ~$1 — output streams below, do not kill it"; }

verdict() { # verdict <task> <PROVEN|UNPROVEN|BROKEN> <note>
  local task=$1 v=$2; shift 2
  printf '%s\t%s\t%s\n' "$task" "$v" "$*" >>"$TSV"
  case "$v" in
    PROVEN)   log "${G}  ▸ $task PROVEN${O} — $*" ;;
    UNPROVEN) log "${Y}  ▸ $task UNPROVEN${O} — $*" ;;
    BROKEN)   log "${R}  ▸ $task BROKEN${O} — $*" ;;
  esac
}

wanted() { # wanted <section-key>
  [ ${#WANT[@]} -eq 0 ] && return 0
  local k
  for k in "${WANT[@]}"; do [ "$k" = "$1" ] && return 0; done
  return 1
}

# --- revert everything on exit ---------------------------------------------

CLEANUP=()
defer() { CLEANUP+=("$1"); }
cleanup() {
  log ""
  head2 "cleanup"
  local i
  for ((i=${#CLEANUP[@]}-1; i>=0; i--)); do
    log "\$ ${CLEANUP[i]}"
    eval "${CLEANUP[i]}" >>"$LOG" 2>&1 || log "  (cleanup step failed — check the tree by hand)"
  done
  log ""
  log "${B}tree after cleanup:${O}"
  git status --porcelain | sed 's/^/    /' | tee -a "$LOG"
  log ""
  log "transcript: $LOG"
  log "verdicts:   $TSV"
  column -t -s $'\t' "$TSV" 2>/dev/null || cat "$TSV"
}
trap cleanup EXIT INT TERM

BASELINE=$(git status --porcelain)
log "Phase 0 audit — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "HEAD: $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
log "dirty at start:"; printf '%s\n' "$BASELINE" | sed 's/^/    /' | tee -a "$LOG"

have_docker() { command -v docker >/dev/null && docker info >/dev/null 2>&1; }

# Poll until a URL answers. `sleep N` is a guess; a container that needed N+1
# seconds reported an empty body and the section read as UNPROVEN.
wait_for() { # wait_for <url> <seconds>
  local url=$1 limit=${2:-30} i=0
  while [ "$i" -lt "$limit" ]; do
    curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null && { log "  ready after ${i}s: $url"; return 0; }
    i=$((i+1)); sleep 1
  done
  log "  ${Y}! not ready after ${limit}s: $url${O}"; return 1
}
if ! have_docker; then
  log "${R}docker is not usable from this shell — every containerised section will be skipped.${O}"
fi

# ===========================================================================
# 0.1  repository skeleton
# ===========================================================================
if wanted 0.1; then
head2 "0.1 repository skeleton"
missing=()
for d in backend bff render frontend docker scripts; do [ -d "$d" ] || missing+=("$d/"); done
for f in .gitignore .env.example; do [ -f "$f" ] || missing+=("$f"); done
run "git ls-files --error-unmatch .env 2>&1 | tail -1"
env_tracked=$?
if [ ${#missing[@]} -eq 0 ] && [ $env_tracked -ne 0 ]; then
  verdict 0.1 PROVEN "all six dirs + .gitignore + .env.example present; .env not tracked"
else
  verdict 0.1 BROKEN "missing: ${missing[*]:-none}; .env tracked: $([ $env_tracked -eq 0 ] && echo YES || echo no)"
fi
fi

# ===========================================================================
# 0.2  Makefile targets + make check green
# ===========================================================================
if wanted 0.2; then
head2 "0.2 Makefile — every DEVELOPMENT command, granular targets included"
need=(up down reset logs shell-api shell-bff psql hooks migrate revision revision-ui
      drizzle-pull test test-api test-bff test-web e2e lint fmt types agents generated check
      fmt-staged fmt-staged-js typecheck-changed typecheck-changed-py)
absent=()
for t in "${need[@]}"; do grep -qE "^$t:" Makefile || absent+=("$t"); done
log "absent targets: ${absent[*]:-none}"
# a skip-guard firing after its task is ticked is a defect per the Makefile header
head2 "0.2b skip-guards that should no longer fire"
run "grep -n 'skip_if_missing' Makefile | wc -l"
for p in compose.yaml backend/alembic.ini bff/drizzle bff/drizzle.config.ts bff/drizzle.crawl.config.ts \
         backend/pyproject.toml bff/package.json frontend/package.json; do
  [ -e "$p" ] && log "  ✓ $p exists (guard inert)" || log "  ${Y}! $p MISSING — its guard still fires${O}"
done
if have_docker; then
  head2 "0.2c make check"
slow "3-6 min"
  if run "make check"; then verdict 0.2 PROVEN "all targets present; make check exit 0"
  else verdict 0.2 BROKEN "make check failed — see log"; fi
else
  verdict 0.2 UNPROVEN "targets present (absent: ${absent[*]:-none}); make check not run (no docker)"
fi
fi

# ===========================================================================
# 0.3 / gate  the three hooks
# ===========================================================================
if wanted 0.3 || wanted gate; then
head2 "0.3 hooks wired"
run "git config core.hooksPath"
hp="$OUT"
run "make hooks"
[ "$hp" = ".githooks" ] || hp=$(git config core.hooksPath)

head2 "gate 1 — commit-msg rejects a long subject"
subj=$(printf 'chore: %0.sx' $(seq 1 120))
# call the hook directly — a --dry-run commit fires no commit-msg hook and
# leaves .git/index.lock behind when it exits early
[ -f .git/index.lock ] && { log "  ${R}stale .git/index.lock — remove it before auditing${O}"; exit 1; }
tmpmsg=$(mktemp); printf '%s\n' "$subj" >"$tmpmsg"
if run ".githooks/commit-msg '$tmpmsg'"; then gate_subject=FAIL; else gate_subject=OK; fi
rm -f "$tmpmsg"
log "  long subject (${#subj} chars) rejected: $gate_subject"
tmpmsg=$(mktemp); printf 'chore: a legitimate subject (0.x)\n' >"$tmpmsg"
run ".githooks/commit-msg '$tmpmsg'" && log "  ✓ a good subject still passes"; rm -f "$tmpmsg"
# boundary: AGENTS.md says "under 72"; the hook rejects >72, so exactly 72 passes
s72=$(printf 'chore: %*s' 64 '' | tr ' ' 'x'); tmpmsg=$(mktemp); printf '%s\n' "$s72" >"$tmpmsg"
.githooks/commit-msg "$tmpmsg" >/dev/null 2>&1 && log "  note: a ${#s72}-char subject passes (hook is >72, AGENTS.md says 'under 72')"
rm -f "$tmpmsg"

head2 "gate 2 — pre-commit rejects a staged .env"
printf 'SECRET=1\n' > .env
defer "rm -f '$REPO/.env' || : >'$REPO/.env'"
run "git add -f .env && .githooks/pre-commit"
if printf '%s' "$OUT" | grep -q 'not committed'; then gate_env=OK
elif printf '%s' "$OUT" | grep -q 'index.lock\|Another git process'; then gate_env="INCONCLUSIVE (git index busy)"
else gate_env=FAIL; fi
run "git reset -q -- .env; rm -f .env"
log "  staged .env rejected: $gate_env"

head2 "gate 3 — pre-push refuses develop (both spellings)"
BARE=$(mktemp -d)/audit-remote.git
git init -q --bare "$BARE"
defer "git remote remove audit-tmp 2>/dev/null; rm -rf '$(dirname "$BARE")'"
run "git remote add audit-tmp '$BARE'"
cur=$(git rev-parse --abbrev-ref HEAD)
# 3a: checked out on develop
run "git stash list | wc -l"
if git rev-parse --verify -q develop >/dev/null; then
  run "git switch -q develop && git push audit-tmp develop; rc=\$?; git switch -q '$cur'; exit \$rc"
  printf '%s' "$OUT" | grep -q 'is protected' && gate_dev_a=OK || gate_dev_a=FAIL
else gate_dev_a=SKIP; fi
log "  push while ON develop refused: $gate_dev_a"
# 3b: the refspec form — push HEAD straight at develop from a feature branch
run "git push audit-tmp HEAD:develop"
if printf '%s' "$OUT" | grep -q 'is protected'; then gate_dev_b=OK
elif printf '%s' "$OUT" | grep -q 'make check failed'; then gate_dev_b="FAIL (got past the branch guard; only make check stopped it)"
else gate_dev_b=FAIL; fi
log "  push HEAD:develop from '$cur' refused: $gate_dev_b"

head2 "gate 4 — a hand-edited .claude/agents file is rejected"
victim=$(ls .claude/agents/*.md | head -1)
cp "$victim" "$victim.audit-bak"; defer "mv -f '$victim.audit-bak' '$victim' 2>/dev/null"
printf '\n<!-- hand edit by the audit -->\n' >> "$victim"
run "git add '$victim' && .githooks/pre-commit"
printf '%s' "$OUT" | grep -q 'These are generated' && gate_gen=OK || gate_gen=FAIL
log "  hand-edited generated role rejected: $gate_gen"
run "git reset -q -- '$victim'; mv -f '$victim.audit-bak' '$victim'"
# and with the escape hatch, the consistency check must still catch it
printf '\n<!-- hand edit by the audit -->\n' >> "$victim"
run "git add '$victim' && SPYDRA_REGEN=1 .githooks/pre-commit"
printf '%s' "$OUT" | grep -q 'disagree' && gate_gen2=OK || gate_gen2=FAIL
log "  ... still rejected under SPYDRA_REGEN=1 (gen-agents --check): $gate_gen2"
run "git reset -q -- '$victim'; git checkout -- '$victim'"

head2 "0.3b pre-commit timing (budget 10 s)"
if have_docker; then
  touch backend/spydra/api/healthz.py
  run "git add backend/spydra/api/healthz.py"
  now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }
  t0=$(now_ms); .githooks/pre-commit >>"$LOG" 2>&1; t1=$(now_ms)
  ms=$(( t1 - t0 )); log "  pre-commit on one staged .py: ${ms} ms"
  run "git reset -q -- backend/spydra/api/healthz.py"
else
  ms=-1; log "  ${Y}not timed — needs docker${O}"
fi

if [ "$hp" = ".githooks" ] && [ "$gate_subject" = OK ] && [ "$gate_env" = OK ] \
   && [ "$gate_gen" = OK ] && [ "$gate_gen2" = OK ] && [ "$gate_dev_b" = OK ] \
   && [ "$ms" -ge 0 ] && [ "$ms" -lt 10000 ]; then
  verdict 0.3 PROVEN "all four gate checks bite; pre-commit ${ms} ms"
elif [ "$gate_dev_b" != OK ]; then
  verdict 0.3 BROKEN "pre-push guards the CHECKED-OUT branch name only: 'git push <remote> HEAD:develop' from a feature branch was NOT refused"
else
  verdict 0.3 UNPROVEN "subject=$gate_subject env=$gate_env gen=$gate_gen gen+REGEN=$gate_gen2 develop-on=$gate_dev_a develop-refspec=$gate_dev_b timing=${ms}ms"
fi
fi

if ! have_docker; then
  log ""; log "${R}stopping before the containerised sections — docker required.${O}"
  exit 0
fi

# ===========================================================================
# 0.4  Dockerfiles — and the worker really has no browser
# ===========================================================================
if wanted 0.4; then
head2 "0.4 images build; worker carries no browser"
slow "5-15 min on a cold cache"
run "ls docker/*.Dockerfile"
run "docker compose build"
built=$?
run "docker compose run --rm --no-deps worker sh -lc 'python -c \"import playwright\" 2>&1; ls /ms-playwright 2>&1; which chromium chrome 2>&1; echo probe-done'"
worker_clean=$(printf '%s' "$OUT" | grep -ci 'ModuleNotFoundError\|No such file')
log "  worker browser probe: expect ModuleNotFoundError + no /ms-playwright"
if [ $built -eq 0 ] && [ "$worker_clean" -ge 2 ]; then
  verdict 0.4 PROVEN "five images build; worker has no playwright and no browser"
else
  verdict 0.4 UNPROVEN "build rc=$built; worker probe matched $worker_clean/2 negative signals — read the log"
fi
fi

# ===========================================================================
# 0.5  compose topology
# ===========================================================================
if wanted 0.5; then
head2 "0.5 compose topology"
run "docker compose config --services | sort | tr '\n' ' '"
svc=$(printf '%s' "$OUT" | wc -w)
run "docker compose config | grep -nE 'shm_size|egress|extra_hosts|pgdata|venv|bff_modules|web_modules'"
run "docker compose up -d && docker compose ps"
up=$?
head2 "0.5b ADR-0023 — render must not resolve api or db"
run "docker compose exec -T render node -e \"
  const probe = async (h,p) => { try { await fetch('http://'+h+':'+p+'/'); console.log(h+': REACHABLE — ISOLATION BROKEN'); } catch(e) { console.log(h+': '+e.cause?.code); } };
  (async()=>{ await probe('api',8000); await probe('db',5432); })();\""
iso=$(printf '%s' "$OUT" | grep -c 'ENOTFOUND\|EAI_AGAIN')
if [ "$svc" -eq 7 ] && [ $up -eq 0 ] && [ "$iso" -ge 2 ]; then
  verdict 0.5 PROVEN "7 services, stack up, render cannot resolve api or db"
else
  verdict 0.5 UNPROVEN "services=$svc up=$up isolation-signals=$iso/2"
fi
fi

# ===========================================================================
# 0.6  SSE unbuffered THROUGH THE EDGE — assert on arrival gaps
#      and on the route the Caddyfile actually gives flush_interval -1
# ===========================================================================
if wanted 0.6; then
head2 "0.6 SSE arrival gaps through the edge"
slow "40 s"
run "docker compose up -d edge api"

# The Caddyfile is a read-only bind mount and Caddy does NOT watch it. Worse,
# `docker compose up -d edge` is a no-op when only the file's CONTENTS changed
# — the service definition is identical — so the container keeps serving the
# config it loaded at boot. Every "the fix did not work" reading of this
# section traces back to here. Validate, then reload.
run "docker compose exec -T edge caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile"
if [ $? -ne 0 ]; then
  log "  ${R}the Caddyfile does not validate — fix it before reading anything below${O}"
else
  run "docker compose exec -T edge caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile"
  [ $? -ne 0 ] && { log "  reload failed, falling back to a restart"; run "docker compose restart edge"; }
fi

# A 502 here is the edge reporting an upstream that has not finished booting,
# not a routing answer. Wait for the api before asking anything about routes.
wait_for "http://127.0.0.1:8080/api/crawler/healthz" 60 || \
  log "  ${R}the api never answered — every reading below is meaningless${O}"
log "The Caddyfile gives flush_interval -1 to ONE handle: /api/crawler/runs/*/events."
log "The smoke route now lives at /api/crawler/runs/__smoke/events so the proof"
log "traverses that handle. Under the old /api/crawler/__smoke/sse it fell through"
log "to the general handle /api/crawler/* and measured Caddy's defaults instead"
log "(phase-0 audit F2). Both are measured below; the second must now 404."

SSE_PROD=/api/crawler/runs/__smoke/events
SSE_OLD=/api/crawler/__smoke/sse

gaps() { # gaps <url> — arrival delta per frame, measured on arrival not in the payload
  curl -sN --max-time 30 "$1" | perl -ne '
    BEGIN { use Time::HiRes qw(time); $| = 1; $n = 0; }
    next unless /^data:/;
    my $t = time;
    if ($p) { printf("  frame %d  gap %.2f s\n", $n, $t - $p) }
    else    { print "  frame 0  (first)\n" }
    $p = $t; $n++;
    END { printf("  frames: %d\n", $n) }'
}

head2 "0.6a does the route match the unbuffered handle?"
run "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080$SSE_PROD"
prod_code="$OUT"
run "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080$SSE_OLD"
old_code="$OUT"
log "  $SSE_PROD -> HTTP $prod_code   (want 200)"
log "  $SSE_OLD -> HTTP $old_code   (want 404 — the old path is gone)"

head2 "0.6b arrival gaps on the production pattern, plain"
if [ "$prod_code" = "200" ]; then
  log "  direct from the api, no edge:"
  gaps "http://127.0.0.1:8000$SSE_PROD" | tee -a "$LOG"
  log "  through the edge — this is the measurement 0.6 asks for:"
  gaps "http://127.0.0.1:8080$SSE_PROD" | tee -a "$LOG"
  log "  (batching reads as a ~5 s first frame then gaps near 0.00)"
  plain_ok=$?
else
  log "  ${R}skipped — the route did not answer 200${O}"
  plain_ok=1
fi

head2 "0.6c the compression path — a browser always asks for it, curl -N does not"
log "  The site block runs 'encode zstd gzip' ahead of every handle, so this is"
log "  a second way to reintroduce buffering. caddy:2-alpine is a floating tag;"
log "  caddyserver/caddy#6293 (encode delaying SSE) was fixed in PR #7905,"
log "  2026-07-31, so whether this stack is affected depends on the tag."
run "docker compose exec -T edge caddy version"
log "  is the stream being COMPRESSED? (GET, not HEAD — HEAD on a stream tells"
log "  you nothing, and reading gzip bytes as text reports zero frames)"
run "curl -sN --max-time 8 -D- -o /dev/null -H 'Accept-Encoding: gzip, zstd' http://127.0.0.1:8080$SSE_PROD | grep -i 'content-encoding\|content-type\|transfer-encoding'"
enc="$OUT"
if printf '%s' "$enc" | grep -qi 'content-encoding'; then
  log "  ${R}✗ the event stream carries a content-encoding header — 'encode zstd gzip'"
  log "    is compressing SSE. Exclude text/event-stream from encode, or move the"
  log "    encode directive inside the non-SSE handles.${O}"
  sse_encoded=1
else
  log "  ${G}✓ no content-encoding — encode is leaving the event stream alone${O}"
  sse_encoded=0
fi
log "  gaps WITH Accept-Encoding, decoded (--compressed), the way a browser reads it:"
curl -sN --compressed --max-time 30 -H 'Accept-Encoding: gzip, zstd' "http://127.0.0.1:8080$SSE_PROD" | perl -ne '
  BEGIN { use Time::HiRes qw(time); $| = 1; $n = 0; }
  next unless /^data:/;
  my $t = time;
  if ($p) { printf("  frame %d  gap %.2f s\n", $n, $t - $p) } else { print "  frame 0  (first)\n" }
  $p = $t; $n++;
  END { printf("  frames: %d\n", $n) }' | tee -a "$LOG"

head2 "0.6d verdict"
log "  Read the gaps above. Six frames at ~1.00 s each, on BOTH the plain and"
log "  the Accept-Encoding run, through :8080, is the proof. Anything else is not."
if [ "$prod_code" = "200" ] && [ "$old_code" = "404" ] && [ "${sse_encoded:-1}" = "1" ]; then
  verdict 0.6 BROKEN "the route is right — it matches /api/crawler/runs/*/events, so rule order and flush_interval -1 are exercised — but 'encode zstd gzip' is COMPRESSING the event stream (content-encoding present on a text/event-stream response). A browser always sends Accept-Encoding, so this is the production path. Fix the Caddyfile, then re-run."
elif [ "$prod_code" = "200" ] && [ "$old_code" = "404" ]; then
  verdict 0.6 PROVEN "the smoke route now matches the Caddyfile's /api/crawler/runs/*/events handle, so the rule order and flush_interval -1 are exercised; gaps measured plain and with Accept-Encoding (read them above — this verdict asserts the ROUTE is right, the gaps are yours to eyeball)"
elif [ "$prod_code" = "502" ] || [ "$prod_code" = "000" ]; then
  verdict 0.6 UNPROVEN "HTTP $prod_code from the edge means the api upstream was not reachable, so nothing was measured. This is the harness, not the config — bring the stack up and re-run: bash scripts/audit-phase0.sh 0.6"
else
  verdict 0.6 UNPROVEN "prod route HTTP $prod_code (want 200), old route HTTP $old_code (want 404). Until the smoke route matches /api/crawler/runs/*/events the measurement says nothing about the production SSE path (F2)."
fi
fi

# ===========================================================================
# 0.7  the BFF role cannot write crawl — FROM A FRESH VOLUME
# ===========================================================================
if wanted 0.7; then
head2 "0.7 grants, from a fresh volume"
slow "2 min — this DROPS the dev database volume"
if [ "$KEEP_DB" = "1" ]; then
  verdict 0.7 UNPROVEN "KEEP_DB=1 — fresh-volume proof skipped"
else
  run "make reset"
  run "docker compose up -d db && sleep 6 && docker compose ps db"
  run "docker compose logs db | grep -i '10-schemas' | tail -5"
  run "docker compose exec -T db psql -U spydra -c '\\\\dn' -c '\\\\du'"
  if run "make verify-grants"; then
    verdict 0.7 PROVEN "fresh volume, init-schemas.sql ran, bff INSERT rejected / SELECT allowed / api cannot see ui"
  else
    verdict 0.7 BROKEN "make verify-grants failed on a fresh volume — see log"
  fi
fi
fi

# ===========================================================================
# 0.8  backend: healthz, lint, and the import contract's teeth
# ===========================================================================
if wanted 0.8; then
head2 "0.8 backend"
run "docker compose up -d api"
wait_for "http://127.0.0.1:8080/api/crawler/healthz" 45
run "curl -s http://127.0.0.1:8080/api/crawler/healthz"
hz="$OUT"
run "make lint-api"
lint_rc=$?
head2 "0.8b import contract — it currently SKIPS (no spydra/domain). Give it a domain to judge."
mkdir -p backend/spydra/domain
defer "rm -rf '$REPO/backend/spydra/domain'"
cat > backend/spydra/domain/__init__.py <<'PY'
PY
cat > backend/spydra/domain/_audit_violation.py <<'PY'
from spydra.adapters.postgres import frontier  # must be rejected
from ..adapters import postgres                # level-2 relative, must be rejected
PY
run "docker compose run --rm --no-deps -T api pytest -q tests/test_import_contracts.py"
teeth=$?
run "rm -rf backend/spydra/domain"
if [ $lint_rc -eq 0 ] && printf '%s' "$hz" | grep -q '"status":"ok"' && [ $teeth -ne 0 ]; then
  verdict 0.8 PROVEN "healthz 200 through the edge; ruff+mypy clean; import contract failed on an injected violation (teeth) and skips only because spydra/domain does not exist yet"
else
  verdict 0.8 UNPROVEN "healthz=$hz lint_rc=$lint_rc contract-teeth-rc=$teeth (nonzero expected)"
fi
fi

# ===========================================================================
# 0.9  bff: healthz + OpenAPI published
# ===========================================================================
if wanted 0.9; then
head2 "0.9 bff"
run "docker compose up -d bff"
wait_for "http://127.0.0.1:8080/api/ui/healthz" 45
run "curl -s http://127.0.0.1:8080/api/ui/healthz"
bhz="$OUT"
run "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/openapi.json"
oc="$OUT"
run "curl -s http://127.0.0.1:3000/openapi.json | head -c 300"
run "make lint-bff"
blint=$?
if printf '%s' "$bhz" | grep -q '"status":"ok"' && [ "$oc" = "200" ] && [ $blint -eq 0 ]; then
  verdict 0.9 PROVEN "healthz via edge, /openapi.json 200, eslint+prettier+tsc clean"
else
  verdict 0.9 UNPROVEN "healthz=$bhz openapi=$oc lint_rc=$blint"
fi
fi

# ===========================================================================
# 0.10  drizzle chain: generate -> migrate -> down -> migrate, from empty
# ===========================================================================
if wanted 0.10; then
head2 "0.10 drizzle wiring"
run "grep -n \"schemaFilter\" bff/drizzle.config.ts bff/drizzle.crawl.config.ts"
if [ "$KEEP_DB" = "1" ]; then
  verdict 0.10 UNPROVEN "KEEP_DB=1 — needs a reset db"
else
  run "make reset && docker compose up -d db && sleep 6"
  run "make migrate-ui"
  u1=$?
  run "docker compose exec -T db psql -U spydra -c '\\\\dt ui.*' -c 'select count(*) from drizzle.__drizzle_migrations'"
  run "make migrate-down-ui"
  d1=$?
  run "docker compose exec -T db psql -U spydra -c '\\\\dn'"
  run "make migrate-ui"
  u2=$?
  head2 "0.10b the drizzle guard's teeth"
  cp bff/drizzle/0000_drizzle_probe.sql /tmp/audit-0000.sql
  defer "cp -f /tmp/audit-0000.sql '$REPO/bff/drizzle/0000_drizzle_probe.sql'"
  printf '\nCREATE TABLE crawl.evil (id int);\n' >> bff/drizzle/0000_drizzle_probe.sql
  run "make test-bff"
  g1=$?
  cp -f /tmp/audit-0000.sql bff/drizzle/0000_drizzle_probe.sql
  mv bff/drizzle/0000_drizzle_probe.down.sql /tmp/audit-0000.down.sql
  defer "cp -f /tmp/audit-0000.down.sql '$REPO/bff/drizzle/0000_drizzle_probe.down.sql' 2>/dev/null"
  if [ -e bff/drizzle/0000_drizzle_probe.down.sql ]; then
    log "  ${R}the .down.sql is still present — the teeth test below proves nothing${O}"
  else
    log "  .down.sql removed; the guard must now fail"
  fi
  # A bind mount can lag a container start by a beat on Docker Desktop.
  sleep 2
  run "docker compose run --rm --no-deps -T bff sh -c 'ls drizzle/'"
  run "make test-bff"
  g2=$?
  cp -f /tmp/audit-0000.down.sql bff/drizzle/0000_drizzle_probe.down.sql
  run "git status --porcelain -- bff/drizzle"
  run "make test-bff"
  g3=$?
  if [ $u1 -eq 0 ] && [ $d1 -eq 0 ] && [ $u2 -eq 0 ] && [ $g1 -ne 0 ] && [ $g2 -ne 0 ] && [ $g3 -eq 0 ]; then
    verdict 0.10 PROVEN "generate->migrate->down->migrate green from empty; guard fails on a crawl. mention and on a missing .down.sql, and is clean again after revert"
  else
    verdict 0.10 UNPROVEN "up=$u1 down=$d1 up2=$u2 crawl-teeth=$g1 downsql-teeth=$g2 restored=$g3"
  fi
fi
fi

# ===========================================================================
# 0.11  render sidecar
# ===========================================================================
if wanted 0.11; then
head2 "0.11 render sidecar"
run "docker compose up -d render && sleep 8 && curl -s http://127.0.0.1:3001/healthz"
rhz="$OUT"
run "curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:3001/render -H 'content-type: application/json' -d '{\"url\":\"not-a-url\"}'"
r422="$OUT"
run "curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:3001/render -H 'content-type: application/json' -d 'not json'"
r400="$OUT"
run "make test-bff >/dev/null 2>&1; docker compose run --rm --no-deps render node --test"
rt=$?
log "  (the 503 backpressure proof needs three held contexts — see render/tests and the 0.11 handoff note; not re-run here)"
if printf '%s' "$rhz" | grep -q contexts_max && [ "$r422" = "422" ] && [ "$r400" = "400" ] && [ $rt -eq 0 ]; then
  verdict 0.11 PROVEN "healthz shape, 422 on a bad URL, 400 on bad JSON, unit suite green"
else
  verdict 0.11 UNPROVEN "healthz=$rhz 422=$r422 400=$r400 tests_rc=$rt"
fi
fi

# ===========================================================================
# 0.12  the palette guard — inject bg-red-500 and watch it fail
# ===========================================================================
if wanted 0.12; then
head2 "0.12 palette guard teeth"
victim=frontend/src/App.tsx
[ -f "$victim" ] || victim=$(ls frontend/src/*.tsx | head -1)
cp "$victim" /tmp/audit-app.tsx; defer "cp -f /tmp/audit-app.tsx '$REPO/$victim'"
run "make test-web"
pre=$?
perl -0pi -e 's/className="/className="bg-red-500 /' "$victim" || sed -i '' 's/<div/<div className="bg-red-500"/' "$victim"
run "grep -n 'bg-red-500' '$victim'"
run "make test-web"
inj=$?
cp -f /tmp/audit-app.tsx "$victim"
# second spelling: the arbitrary value
perl -0pi -e 's/className="/className="bg-[#dc2626] /' "$victim"
run "make test-web"
arb=$?
cp -f /tmp/audit-app.tsx "$victim"
# third: the structural line
cp design/tokens/tailwind-theme.css /tmp/audit-tw.css; defer "cp -f /tmp/audit-tw.css '$REPO/design/tokens/tailwind-theme.css'"
perl -0pi -e 's/--color-\*: initial;//' design/tokens/tailwind-theme.css
run "make test-web"
struct=$?
cp -f /tmp/audit-tw.css design/tokens/tailwind-theme.css
run "make test-web"
post=$?
if [ $pre -eq 0 ] && [ $inj -ne 0 ] && [ $arb -ne 0 ] && [ $struct -ne 0 ] && [ $post -eq 0 ]; then
  verdict 0.12 PROVEN "green; fails on bg-red-500, on bg-[#dc2626], and on removing --color-*: initial; green again after revert"
else
  verdict 0.12 UNPROVEN "baseline=$pre bg-red-500=$inj arbitrary=$arb structural=$struct restored=$post (middle three must be nonzero)"
fi
fi

# ===========================================================================
# 0.13  both migration chains cycle, from empty
# ===========================================================================
if wanted 0.13; then
head2 "0.13 both chains cycle from empty"
slow "3 min — this DROPS the dev database volume"
if [ "$KEEP_DB" = "1" ]; then
  verdict 0.13 UNPROVEN "KEEP_DB=1 — the cycle must start from an empty database"
else
  run "make reset && docker compose up -d db && sleep 6"
  run "make migrate"; m1=$?
  run "docker compose exec -T db psql -U spydra -c 'select version_num from crawl.alembic_version' -c '\\\\dt ui.*' -c 'select count(*) from drizzle.__drizzle_migrations'"
  run "make migrate-down"; m2=$?
  run "docker compose exec -T db psql -U spydra -c 'select count(*) from crawl.alembic_version' -c '\\\\dn'"
  run "make migrate"; m3=$?
  run "docker compose exec -T db psql -U spydra -c 'select version_num from crawl.alembic_version' -c '\\\\dt ui.*'"
  if [ $m1 -eq 0 ] && [ $m2 -eq 0 ] && [ $m3 -eq 0 ]; then
    verdict 0.13 PROVEN "migrate -> migrate-down -> migrate all exit 0 from an empty volume; alembic version and ui.drizzle_probe restored"
  else
    verdict 0.13 BROKEN "migrate=$m1 down=$m2 migrate=$m3"
  fi
fi
fi

# ===========================================================================
# 0.14  generated-artifact chain detects drift — both directions
# ===========================================================================
if wanted 0.14; then
head2 "0.14 drift detection"
slow "4-8 min, it regenerates every artifact five times"
run "docker compose up -d db"
wait_for_db() { local i=0; while [ "$i" -lt 45 ]; do docker compose exec -T db pg_isready -U spydra >/dev/null 2>&1 && return 0; i=$((i+1)); sleep 1; done; return 1; }
wait_for_db && log "  db accepting connections"
# The committed crawl.generated.ts was introspected with BOTH chains applied —
# crawl.alembic_version included. Section 0.10 leaves the database with `ui`
# migrated and `crawl` empty, so without this the baseline reads as drift and
# every teeth result below is measured against a broken baseline.
log "  restoring both chains first — the committed artifacts were generated with both applied"
run "make migrate"
run "make generated && git status --porcelain -- frontend/src/api bff/src/db/schema .claude .cursor .opencode .agents"
base="$OUT"
log "  baseline drift (should be empty): '${base}'"
run "make -s generated-check"; gc0=$?

head2 "0.14a an UNCOMMITTED hand-edit is not what generated-check catches"
log "  generated-check runs 'make generated' FIRST, then reads git status — so a"
log "  hand-edit to a file in the working tree is overwritten by the regeneration"
log "  before the check looks. That is by design, and it is why the guarantee is"
log "  split across two mechanisms:"
log "    · commit time — the pre-commit hook refuses a staged generated file"
log "      (proven in the gate section: 'hand-edited generated role rejected')"
log "    · check time  — generated-check catches an artifact that is STALE with"
log "      respect to its source, which is 0.14c below"
log "  The audit previously tested the uncommitted case and scored it as a"
log "  failure. It was the test that was wrong, not the chain."

head2 "0.14c edit the CANONICAL role without regenerating"
rf=docs/agents/spydra-ops.md
cp "$rf" /tmp/audit-role.md; defer "cp -f /tmp/audit-role.md '$REPO/$rf'"
printf '\nAn audit sentence.\n' >> "$rf"
run "python3 scripts/gen-agents.py --check"; gc3=$?
run "make -s generated-check"; gc4=$?
cp -f /tmp/audit-role.md "$rf"
run "make agents && git status --porcelain -- .claude .cursor .opencode .agents"

head2 "0.14d a crawl column change must break the BFF artifact"
log "  skipped by default: it needs a throwaway alembic revision against the dev db."
log "  run it by hand if you want it re-proven — the 0.14 handoff log records the"
log "  original run (crawl.proof -> stale crawl.generated.ts -> make check failed)."

run "make -s generated-check"; gc5=$?
if [ $gc0 -eq 0 ] && [ $gc3 -ne 0 ] && [ $gc4 -ne 0 ] && [ $gc5 -eq 0 ]; then
  verdict 0.14 PROVEN "clean at baseline with both chains applied; an edited canonical role with no 'make agents' fails BOTH gen-agents --check and generated-check; clean again after regenerating. The hand-edit-a-generated-file case is enforced at commit time by pre-commit (see the gate section), not by generated-check, which regenerates before it reads git status."
else
  verdict 0.14 UNPROVEN "baseline=$gc0 (want 0) gen-agents--check=$gc3 (want nonzero) role-unregenerated=$gc4 (want nonzero) restored=$gc5 (want 0)"
fi
fi

# ===========================================================================
# 0.15  the suites actually run
# ===========================================================================
if wanted 0.15; then
head2 "0.15 suites run rather than skip"
run "make test-api"; ta=$?
run "make test-bff"; tb=$?
run "make test-web"; tw=$?
log "  a 'skip <target>' line in any of the three means the guard still fires"
if [ $ta -eq 0 ] && [ $tb -eq 0 ] && [ $tw -eq 0 ]; then
  verdict 0.15 PROVEN "pytest, node:test and vitest all run and pass"
else
  verdict 0.15 BROKEN "api=$ta bff=$tb web=$tw"
fi
fi

# ===========================================================================
# 0.16  CI steps, on a clean checkout
# ===========================================================================
if wanted 0.16; then
head2 "0.16 CI steps on a clean checkout"
slow "5-15 min, it builds from a fresh clone"
run "cat .github/workflows/check.yml | grep -nE 'run:|uses:'"
CLONE=$(mktemp -d)/spydra-ci
defer "rm -rf '$(dirname "$CLONE")'"
run "git clone -q --no-hardlinks '$REPO' '$CLONE' && cd '$CLONE' && git switch -q --detach $(git rev-parse HEAD) && ls"
log "  replicating the workflow's steps in $CLONE (COMPOSE project is shared — this"
log "  reuses the same volumes, which is the honest limit of a local replication):"
run "cd '$CLONE' && docker compose build"; c1=$?
run "cd '$CLONE' && docker compose up -d db && sleep 6"; c2=$?
run "cd '$CLONE' && make migrate"; c3=$?
run "cd '$CLONE' && make migrate-down"; c4=$?
run "cd '$CLONE' && make check"; c5=$?
log "  NOTE: the workflow never runs 'make migrate' again after migrate-down, so"
log "  the full cycle 0.13 demands is not CI-protected; and neither 'make"
log "  verify-grants' nor any SSE assertion appears in check.yml, so 0.6 and 0.7"
log "  have no regression guard."
if [ $c1 -eq 0 ] && [ $c3 -eq 0 ] && [ $c4 -eq 0 ] && [ $c5 -eq 0 ]; then
  verdict 0.16 PROVEN "every check.yml step runs green on a clean clone (the workflow itself is inert until a remote exists)"
else
  verdict 0.16 UNPROVEN "build=$c1 db=$c2 migrate=$c3 down=$c4 check=$c5"
fi
fi

# ===========================================================================
# 0.17  the handoff — evidence, not a re-run
# ===========================================================================
if wanted 0.17; then
head2 "0.17 agent handoff smoke test"
run "git log --oneline --graph develop..HEAD | grep -i '0.17' | head -20"
run "cat .tasks/chore-0.17-hello-slice.md | head -40"
run "git log --merges --oneline | head -5"
verdict 0.17 UNPROVEN "not re-runnable by a script: the artefact is .tasks/chore-0.17-hello-slice.md plus the merge of chore/0.17-hello-slice, both present. Whether the handoff still works is only answerable by running a slice, which is phase 1's first task."
fi

head2 "done"
