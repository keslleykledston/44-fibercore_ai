SHELL := /bin/bash

.PHONY: validate test-api compose-config up down logs
validate:
	python tests/validate_kit.py

test-api:
	cd starter/apps/api && python -m pytest -q

compose-config:
	cd infra/compose && FIBERCORE_DB_PASSWORD=$${FIBERCORE_DB_PASSWORD:-dev_only_change_this_password} docker compose config --quiet

up:
	cd infra/compose && FIBERCORE_DB_PASSWORD=$${FIBERCORE_DB_PASSWORD:-dev_only_change_this_password} docker compose up --build -d

down:
	cd infra/compose && FIBERCORE_DB_PASSWORD=$${FIBERCORE_DB_PASSWORD:-dev_only_change_this_password} docker compose down

logs:
	cd infra/compose && docker compose logs -f --tail=100
