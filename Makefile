# ---------------------------------------------------------------------------
# Spydra — every command is a make target, and every target runs in a
# container (ADR-0010). The two exceptions are `agents` and `hooks`, plain
# host commands on purpose: they must work from any tool's terminal before
# any image exists (AGENTS.md rule 1).
#
# Phase 0 rule (BUILD_PLAN 0.2): a target whose package or compose file does
# not exist yet SKIPS with a message instead of failing, so `make check` is
# green from the first commit of the phase and can gate the rest of it.
# Each guard is removed by the task that builds the thing it guards; a guard
# firing after its task is ticked is a defect.
# ---------------------------------------------------------------------------

COMPOSE := docker compose

# Integration tests run against their own database, never the dev one
# (TESTING.md §1: SKIP LOCKED, DISTINCT ON and partial unique indexes rule
# SQLite out, so the suite needs real Postgres — and a suite that shares the
# dev database destroys the data you were looking at). Kept here as well as
# in compose's x-py-env so `make test-api` reads it without the api service
# having to be the thing that defines it.
TEST_DATABASE_URL := postgresql+asyncpg://spydra_api:spydra@db:5432/spydra_test

# First line of a recipe, joined to the command with && so the whole target
# stops when the guard trips:
#   $(call skip_if_missing,compose.yaml) && $(COMPOSE) up -d
skip_if_missing = @test -e "$(1)" || { echo "·  skip $@ — $(1) does not exist yet"; exit 0; }

# A literal newline, for flattening $(FILES) — callers (the hooks) pass staged
# paths newline-separated, and a raw newline inside a recipe breaks sh -c.
define NL


endef
flat = $(subst $(NL), ,$(1))

.DEFAULT_GOAL := help

.PHONY: help hooks agents agents-check \
        up down reset reset-deps logs ps \
        shell-api shell-bff shell-web psql verify-grants \
        migrate migrate-api migrate-ui migrate-down migrate-down-api \
        migrate-down-ui revision revision-ui drizzle-pull drizzle-studio \
        test test-api test-bff test-web test-render e2e seed-dev \
        lint lint-api lint-bff lint-web fmt \
        fmt-staged fmt-staged-js typecheck-changed typecheck-changed-py \
        types types-crawler types-ui generated generated-check check

help: ## show the targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "} {printf "  \033[1;36m%-22s\033[0m %s\n", $$1, $$2}' | sort

# --- host-only (the two sanctioned exceptions, AGENTS.md rule 1) -----------

hooks: ## wire .githooks — run once per clone
	chmod +x .githooks/*
	git config core.hooksPath .githooks
	@echo "·  hooks wired to .githooks/"

agents: ## regenerate agent adapters from docs/agents/
	python3 scripts/gen-agents.py

agents-check:
	python3 scripts/gen-agents.py --check

# --- lifecycle ---------------------------------------------------------------

up: ## build and start the whole stack
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) up -d --build

down: ## stop the stack, keep volumes
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) down

reset: ## stop and DROP every volume, database included
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) down -v

reset-deps: ## drop the venv/node_modules volumes only (corrupt-install fix, DEVELOPMENT.md)
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) stop && \
	docker volume rm -f spydra_venv spydra_bff_modules spydra_web_modules || true

logs: ## follow all service logs
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) logs -f --tail=50

ps: ## container status
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) ps

# --- shells ------------------------------------------------------------------

shell-api: ## bash inside the api container
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) run --rm api bash

shell-bff: ## bash inside the bff container
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) run --rm bff bash

shell-web: ## sh inside the web container
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) run --rm web sh

psql: ## psql into the dev database (both schemas)
	$(call skip_if_missing,compose.yaml) && $(COMPOSE) exec db psql -U spydra

verify-grants: ## PROVE the BFF role cannot write crawl (spec 010 §3, BUILD_PLAN 0.7)
	$(call skip_if_missing,compose.yaml) && \
	echo "·  as spydra_api (schema owner): create a throwaway crawl.runs" && \
	$(COMPOSE) exec -T db psql postgres://spydra_api:spydra@localhost:5432/spydra \
	  -c "CREATE TABLE crawl.runs (id integer)" >/dev/null && \
	echo "·  as spydra_bff: INSERT must be REJECTED" && \
	if $(COMPOSE) exec -T db psql postgres://spydra_bff:spydra@localhost:5432/spydra \
	    -c "INSERT INTO crawl.runs VALUES (1)" >/dev/null 2>/tmp/spydra-grant.err; then \
	  $(COMPOSE) exec -T db psql postgres://spydra_api:spydra@localhost:5432/spydra \
	    -c "DROP TABLE crawl.runs" >/dev/null; \
	  echo "✗ INSERT INTO crawl.runs SUCCEEDED from spydra_bff — the data-ownership boundary is broken"; exit 1; \
	else \
	  grep -q "permission denied" /tmp/spydra-grant.err && echo "  ✓ rejected: $$(grep -m1 'permission denied' /tmp/spydra-grant.err | sed 's/ERROR: //')"; \
	fi; \
	echo "·  as spydra_bff: SELECT must be ALLOWED (aggregation path)" && \
	$(COMPOSE) exec -T db psql postgres://spydra_bff:spydra@localhost:5432/spydra \
	  -c "SELECT count(*) FROM crawl.runs" >/dev/null && echo "  ✓ select granted"; \
	echo "·  as spydra_api: the ui schema must be INVISIBLE" && \
	if $(COMPOSE) exec -T db psql postgres://spydra_api:spydra@localhost:5432/spydra \
	    -c "CREATE TABLE ui.probe (id integer)" >/dev/null 2>&1; then \
	  echo "✗ spydra_api wrote to ui — no route in should exist"; $(COMPOSE) exec -T db psql postgres://spydra_api:spydra@localhost:5432/spydra -c "DROP TABLE crawl.runs" >/dev/null; exit 1; \
	else \
	  echo "  ✓ rejected (no route into ui)"; \
	fi; \
	$(COMPOSE) exec -T db psql postgres://spydra_api:spydra@localhost:5432/spydra \
	  -c "DROP TABLE crawl.runs" >/dev/null && echo "✓ grants hold: bff reads crawl, writes nothing; api never sees ui"

# --- migrations: two chains, two owners (spec 010 §3) ------------------------

migrate: migrate-api migrate-ui ## both chains: alembic (crawl) + drizzle (ui)

migrate-api:
	$(call skip_if_missing,backend/alembic.ini) && $(COMPOSE) run --rm api alembic upgrade head

migrate-ui:
	$(call skip_if_missing,bff/drizzle) && $(COMPOSE) run --rm bff npx drizzle-kit migrate

migrate-down: migrate-down-api migrate-down-ui ## one step back, both chains

migrate-down-api:
	$(call skip_if_missing,backend/alembic.ini) && $(COMPOSE) run --rm api alembic downgrade -1

migrate-down-ui:
	$(call skip_if_missing,bff/drizzle) && $(COMPOSE) run --rm bff npm run migrate:down

revision: ## autogenerate a crawl migration — make revision m="add asset_queue"
	$(call skip_if_missing,backend/alembic.ini) && $(COMPOSE) run --rm api alembic revision --autogenerate -m "$(m)"

revision-ui: ## generate a ui migration — make revision-ui m="add schedules"
	$(call skip_if_missing,bff/drizzle.config.ts) && $(COMPOSE) run --rm bff npx drizzle-kit generate --name "$(m)"

# introspect is deliberately not chained with && — on an empty schema it
# may exit nonzero, and the writer must still produce the honest empty
# artifact deterministically. Needs the db up, so no --no-deps.
drizzle-pull: ## re-introspect crawl → crawl.generated.ts (ADR-0021)
	$(call skip_if_missing,bff/drizzle.crawl.config.ts) && \
	rm -rf bff/.crawl-introspect && \
	$(COMPOSE) run --rm -T bff sh -c \
	  "npx drizzle-kit introspect --config=drizzle.crawl.config.ts; \
	   tsx scripts/write-crawl-generated.ts"

drizzle-studio: ## browse the ui schema
	$(call skip_if_missing,bff/drizzle.config.ts) && $(COMPOSE) run --rm --service-ports bff npx drizzle-kit studio

# --- tests --------------------------------------------------------------------

test: test-api test-bff test-web test-render ## everything

# NOT --no-deps: the suite needs the database up (phase-1 finding F1 — it
# was --no-deps, which made every integration test in TESTING.md §2
# unrunnable, starting with the two the politeness guarantee rests on).
# compose starts `db` and waits for its healthcheck via api's depends_on.
test-api:
	$(call skip_if_missing,backend/pyproject.toml) && $(COMPOSE) run --rm \
		-e DATABASE_URL=$(TEST_DATABASE_URL) api pytest -q

test-bff:
	$(call skip_if_missing,bff/package.json) && $(COMPOSE) run --rm --no-deps bff npm test

test-web:
	$(call skip_if_missing,frontend/package.json) && $(COMPOSE) run --rm --no-deps web npm test

# The sidecar's own suite, which is the half of spec 012 that drives a real
# browser (TESTING.md §1). It had no target at all and so was never gated
# (phase-1 finding F3) — `make check` is the contract in ADR-0022 §3 and an
# ungated service is not covered by it.
test-render:
	$(call skip_if_missing,render/package.json) && $(COMPOSE) run --rm --no-deps render npm test

e2e: ## Playwright against the running stack
	$(call skip_if_missing,frontend/playwright.config.ts) && $(COMPOSE) run --rm --no-deps web npx playwright test

seed-dev: ## two offline fixture domains (arrives with BUILD_PLAN 5.1)
	$(call skip_if_missing,backend/spydra/seed_dev.py) && $(COMPOSE) run --rm --no-deps api python -m spydra.seed_dev

# --- lint and format ------------------------------------------------------------
# ruff + mypy + import-linter live in the api image; eslint + prettier in the
# bff and web images. The bff container also mounts the repo root at /repo so
# prettier can reach root-level docs and yaml — no container else sees them.

lint: lint-api lint-bff lint-web ## ruff + mypy + import-linter + eslint + prettier

lint-api:
	$(call skip_if_missing,backend/pyproject.toml) && $(COMPOSE) run --rm --no-deps api sh -c "ruff check . && mypy ."
	# The domain→adapters import contract is enforced by a stdlib-AST pytest
	# (task 0.8), not import-linter: grimp ships no cp315 aarch64 wheels
	# (ADR-0017 readiness gate), and a test blocks CI where a lint warns.

lint-bff:
	$(call skip_if_missing,bff/package.json) && $(COMPOSE) run --rm --no-deps bff npm run lint

lint-web:
	$(call skip_if_missing,frontend/package.json) && $(COMPOSE) run --rm --no-deps web npm run lint

fmt: ## ruff format + prettier --write
	$(call skip_if_missing,backend/pyproject.toml) && $(COMPOSE) run --rm --no-deps api ruff format .
	$(call skip_if_missing,bff/package.json) && $(COMPOSE) run --rm --no-deps bff npx prettier --write src ../docs ../compose.yaml
	$(call skip_if_missing,frontend/package.json) && $(COMPOSE) run --rm --no-deps web npx prettier --write src

# --- called by .githooks/pre-commit ---------------------------------------------
# FILES comes from the hook as the staged paths, newline separated. The hook
# re-stages whatever the formatters rewrite; formatting fixes a commit, it
# does not block one (WORKFLOW.md §2).

fmt-staged:
	@if [ ! -f backend/pyproject.toml ]; then echo "·  skip $@ — backend/pyproject.toml does not exist yet"; exit 0; fi; \
	files='$(call flat,$(FILES))'; \
	inapi=""; inrepo=""; \
	for f in $$files; do \
	  case "$$f" in \
	    backend/*) inapi="$$inapi /app/$${f#backend/}" ;; \
	    *)         inrepo="$$inrepo /repo/$$f" ;; \
	  esac; \
	done; \
	[ -n "$$inapi$$inrepo" ] && $(COMPOSE) run --rm --no-deps -T api sh -c \
	  "ruff format $$inapi $$inrepo && ruff check --fix $$inapi $$inrepo"

# Split staged files by the package whose container can see them. Root-level
# files (docs, compose.yaml) go to the bff container via its /repo mount.
fmt-staged-js:
	@if [ ! -f compose.yaml ]; then echo "·  skip $@ — no compose stack yet"; exit 0; fi; \
	files=$$(printf '%s\n' '$(call flat,$(FILES))' | tr ' ' '\n'); \
	bff=$$(printf '%s\n' "$$files" | grep '^bff/' | sed 's|^bff/|/app/|' | tr '\n' ' '); \
	web=$$(printf '%s\n' "$$files" | grep '^frontend/' | sed 's|^frontend/|/app/|' | tr '\n' ' '); \
	root=$$(printf '%s\n' "$$files" | grep -v '^bff/\|^frontend/' | sed 's|^|/repo/|' | tr '\n' ' '); \
	if [ -n "$$bff" ] && [ -f bff/package.json ]; then \
	  $(COMPOSE) run --rm --no-deps -T bff sh -c "npx prettier --write $$bff && npx eslint --fix $$bff" || exit 1; \
	fi; \
	if [ -n "$$web" ] && [ -f frontend/package.json ]; then \
	  $(COMPOSE) run --rm --no-deps -T web sh -c "npx prettier --write $$web && npx eslint --fix $$web" || exit 1; \
	fi; \
	if [ -n "$$root" ] && [ -f bff/package.json ]; then \
	  $(COMPOSE) run --rm --no-deps -T bff sh -c "cd /repo && npx prettier --write $$root" || exit 1; \
	fi

typecheck-changed:
	@if [ ! -f bff/package.json ] && [ ! -f frontend/package.json ]; then echo "·  skip $@ — no TS packages yet"; exit 0; fi; \
	files=$$(printf '%s\n' '$(call flat,$(FILES))' | tr ' ' '\n'); \
	if printf '%s\n' "$$files" | grep -q '^bff/' && [ -f bff/package.json ]; then \
	  $(COMPOSE) run --rm --no-deps -T bff tsc --noEmit; \
	fi; \
	if printf '%s\n' "$$files" | grep -q '^frontend/' && [ -f frontend/package.json ]; then \
	  $(COMPOSE) run --rm --no-deps -T web tsc --noEmit; \
	fi

typecheck-changed-py:
	@if [ ! -f backend/pyproject.toml ]; then echo "·  skip $@ — backend/pyproject.toml does not exist yet"; exit 0; fi; \
	files='$(call flat,$(FILES))'; \
	mapped=""; \
	for f in $$files; do \
	  case "$$f" in \
	    backend/*) mapped="$$mapped /app/$${f#backend/}" ;; \
	    *)         mapped="$$mapped /repo/$$f" ;; \
	  esac; \
	done; \
	$(COMPOSE) run --rm --no-deps -T api mypy $$mapped

# --- generated artifacts (ADR-0013, ADR-0021, ADR-0022) -------------------------
# Committed build artifacts, regenerated by make generated; `make check` fails
# if regenerating produces a diff — including a hand edit, which is the same
# failure viewed from the other side.

types: types-crawler types-ui ## regenerate BOTH frontend API schemas

# ADR-0013: the OpenAPI documents are exported by importing the app inside
# its container — no listener, no published port, works in CI on a clean
# checkout. stdout is redirected to a gitignored scratch JSON on the host;
# openapi-typescript (in the isolated frontend/tools/types-gen toolchain —
# it needs the typescript JS API that the Go-port tsc 7 does not ship) then
# runs in the web container, which sees the JSON through the bind mount.

types-crawler: ## api OpenAPI → frontend/src/api/schema.crawler.d.ts
	@test -e backend/pyproject.toml && test -e frontend/package.json \
	  || { echo "·  skip $@ — api or web not scaffolded yet"; exit 0; } && \
	mkdir -p frontend/src/api && \
	$(COMPOSE) run --rm --no-deps -T api \
	  python -c "import json; from spydra.api.main import app; print(json.dumps(app.openapi()))" \
	  > frontend/src/api/openapi.crawler.json && \
	$(COMPOSE) run --rm --no-deps -T web sh -c '\
	  cd tools/types-gen && npm install --no-audit --no-fund --silent && \
	  npx openapi-typescript ../../src/api/openapi.crawler.json -o ../../src/api/schema.crawler.d.ts && \
	  sed -i "1i // GENERATED by \`make types\` — DO NOT EDIT (ADR-0013).\n// Regenerated from the api OpenAPI document; \`make check\` fails on any diff." \
	    ../../src/api/schema.crawler.d.ts'

types-ui: ## bff OpenAPI → frontend/src/api/schema.ui.d.ts
	@test -e bff/package.json && test -e frontend/package.json \
	  || { echo "·  skip $@ — bff or web not scaffolded yet"; exit 0; } && \
	mkdir -p frontend/src/api && \
	$(COMPOSE) run --rm --no-deps -T bff tsx scripts/export-openapi.ts \
	  > frontend/src/api/openapi.ui.json && \
	$(COMPOSE) run --rm --no-deps -T web sh -c '\
	  cd tools/types-gen && npm install --no-audit --no-fund --silent && \
	  npx openapi-typescript ../../src/api/openapi.ui.json -o ../../src/api/schema.ui.d.ts && \
	  sed -i "1i // GENERATED by \`make types\` — DO NOT EDIT (ADR-0013).\n// Regenerated from the bff OpenAPI document; \`make check\` fails on any diff." \
	    ../../src/api/schema.ui.d.ts'

generated: types drizzle-pull agents ## regenerate every committed artifact

check: lint test generated-check ## the gate — CI runs exactly this

generated-check: ## fail if any generated artifact is stale or hand-edited
	@$(MAKE) -s generated
	@out=$$(git status --porcelain -- \
	    frontend/src/api/schema.crawler.d.ts frontend/src/api/schema.ui.d.ts \
	    bff/src/db/schema/crawl.generated.ts \
	    .claude/agents .cursor/rules .opencode/agents .agents/rules); \
	if [ -n "$$out" ]; then \
	  echo "✗ generated artifacts are stale or hand-edited — run 'make generated' and commit:"; \
	  echo "$$out" | sed 's/^/    /'; exit 1; \
	fi
	@echo "·  generated artifacts current"
