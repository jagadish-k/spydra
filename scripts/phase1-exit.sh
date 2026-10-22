#!/usr/bin/env bash
# Phase 1's exit criterion against the live stack (BUILD_PLAN 1.14, ADR-0036).
#
#   1. db, render and the `fixtures` profile service up; the test database
#      migrated and emptied (an exit run never touches the dev database).
#   2. Load render-up.yaml, run the real worker, check: static via httpx, the
#      JS page via the sidecar, AUTO rendered by its second chance, assets.
#   3. Stop render. Load render-down.yaml, check: static unaffected, AUTO
#      recorded static_fallback.
#   4. Put render back, stop the worker and the fixtures.
set -euo pipefail
cd "$(dirname "$0")/.."

files=(-f compose.yaml)
if [ "$(uname -s)" = Linux ]; then
  # See docker/compose.linux.yaml: on Linux Docker Engine the worker cannot
  # reach a sidecar published only on the host's loopback.
  DOCKER_HOST_GATEWAY=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')
  export DOCKER_HOST_GATEWAY
  files+=(-f docker/compose.linux.yaml)
fi
compose() { docker compose "${files[@]}" --profile phase1-exit "$@"; }
TEST_DB=postgresql+asyncpg://spydra_api:spydra@db:5432/spydra_test
in_api() { compose run --rm -T -e DATABASE_URL="$TEST_DB" api "$@"; }

worker=""
cleanup() {
  [ -n "$worker" ] && docker stop -t 30 "$worker" >/dev/null 2>&1 || true
  compose up -d render >/dev/null 2>&1 || true
  compose stop fixtures >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "· stack: db, render, fixtures"
compose up -d --wait db render fixtures
in_api alembic upgrade head >/dev/null
in_api python -m tests.phase1_exit reset

start_worker() {
  worker=$(compose run -d --rm -e DATABASE_URL="$TEST_DB" -e LOG_LEVEL=info worker)
}
load() { in_api python -m spydra.load "$1" | sed -n 's/^run \([0-9]*\).*/\1/p'; }

echo "· run 1: render up"
start_worker
run=$(load tests/fixtures/phase1/render-up.yaml)
in_api python -m tests.phase1_exit render-up "$run"

echo "· run 2: render stopped"
compose stop render >/dev/null
run=$(load tests/fixtures/phase1/render-down.yaml)
in_api python -m tests.phase1_exit render-down "$run"

echo "· worker log (info):"
docker logs "$worker" 2>&1 | tail -20
echo "✓ phase 1 exit"
