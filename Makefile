SHELL := /bin/bash
VENV ?= .venv
PY := $(VENV)/bin/python
COMPOSE := docker compose --env-file .env.dev -f infra/compose/compose.yaml
TEST_PG_PORT ?= 55432

.PHONY: rbac-matrix env-prod up-prod down-prod venv env-dev validate validate-help lint test-api compose-config up down logs
venv:
	test -d $(VENV) || python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e 'apps/api[dev]'

env-dev:  ## gera .env.dev com segredos aleatórios (nunca toca .env)
	@test -f .env.dev || { \
	  echo "FIBERCORE_DB_PASSWORD=$$(openssl rand -hex 16)" > .env.dev; \
	  echo "FIBERCORE_APP_DB_PASSWORD=$$(openssl rand -hex 16)" >> .env.dev; \
	  echo "FIBERCORE_WORKER_DB_PASSWORD=$$(openssl rand -hex 16)" >> .env.dev; \
	  echo "FIBERCORE_RBAC_DB_PASSWORD=$$(openssl rand -hex 16)" >> .env.dev; \
	  echo "FIBERCORE_JWT_SECRET=$$(openssl rand -hex 32)" >> .env.dev; \
	  echo "FIBERCORE_PII_HMAC_KEY=$$(openssl rand -hex 32)" >> .env.dev; \
	  echo "FIBERCORE_JOB_SIGNING_KEY=$$(openssl rand -base64 32)" >> .env.dev; echo ".env.dev criado"; }
	@grep -q '^FIBERCORE_MFA_ENCRYPTION_KEY=' .env.dev || echo "FIBERCORE_MFA_ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')" >> .env.dev

validate: venv
	$(PY) tests/validate_kit.py
	$(PY) tests/validate_help.py
	$(PY) tests/validate_addendum_v22.py

validate-help: venv
	$(PY) tests/validate_help.py

lint: venv
	$(VENV)/bin/ruff check apps/api

test-api: venv  ## sobe Postgres descartável, roda pytest, remove container
	-docker rm -f fc-test-pg fc-test-nats >/dev/null 2>&1
	docker run -d --name fc-test-nats -p 127.0.0.1:54222:4222 nats:2.11-alpine -js >/dev/null
	docker run -d --name fc-test-pg -e POSTGRES_USER=fibercore -e POSTGRES_PASSWORD=test_admin_pw_only \
	  -e POSTGRES_DB=fibercore_test -p 127.0.0.1:$(TEST_PG_PORT):5432 postgres:17-alpine >/dev/null
	@until docker exec fc-test-pg pg_isready -U fibercore >/dev/null 2>&1; do sleep 1; done; sleep 2
	cd apps/api && TEST_NATS_URL=nats://127.0.0.1:54222 TEST_ADMIN_DATABASE_URL=postgresql://fibercore:test_admin_pw_only@127.0.0.1:$(TEST_PG_PORT)/fibercore_test \
	  ../../$(PY) -m pytest -q; rc=$$?; docker rm -f fc-test-pg fc-test-nats >/dev/null; exit $$rc

rbac-matrix: venv  ## regenera docs/security/RBAC_MATRIX.md a partir do código (ADR-0031)
	$(PY) scripts/gen_rbac_matrix.py

compose-config: env-dev
	$(COMPOSE) config --quiet

up: env-dev
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

COMPOSE_PROD := docker compose -p fibercore-prod --env-file .env.prod -f infra/compose/compose.yaml --profile public

env-prod:  ## gera .env.prod (0600) com segredos aleatórios; Caddy atrás do nginx do host (ADR-0016)
	@test -f .env.prod || { umask 077; { \
	  echo "FIBERCORE_DB_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "FIBERCORE_APP_DB_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "FIBERCORE_WORKER_DB_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "FIBERCORE_RBAC_DB_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "FIBERCORE_JWT_SECRET=$$(openssl rand -hex 32)"; \
	  echo "FIBERCORE_PII_HMAC_KEY=$$(openssl rand -hex 32)"; \
	  echo "FIBERCORE_MFA_ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')"; \
	  echo "FIBERCORE_CADDYFILE=Caddyfile.upstream"; \
	  echo "FIBERCORE_INSECURE_COOKIES=0"; \
	  echo "FIBERCORE_TRUSTED_PROXY=true"; \
	  echo "FIBERCORE_PROXY_HTTP_PORT=18480"; \
	  echo "FIBERCORE_API_PORT=18420"; } > .env.prod; echo ".env.prod criado (0600)"; }
	@grep -q '^FIBERCORE_MFA_ENCRYPTION_KEY=' .env.prod || { umask 077; echo "FIBERCORE_MFA_ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')" >> .env.prod; echo "MFA_ENCRYPTION_KEY adicionada ao .env.prod"; }

up-prod: env-prod
	$(COMPOSE_PROD) up -d --build

down-prod:
	$(COMPOSE_PROD) down
