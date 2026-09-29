# Llobregat Express · common commands. Run `make` to list them.

COMPOSE := docker compose
WAIT_TIMEOUT ?= 1800
# The generator's pinned environment (services/generator/uv.lock); .env gives it the credentials.
GENERATOR := uv run --project services/generator --frozen
SEED ?= 0
COUNT ?= 20
FUTURE = $(if $(ALLOW_FUTURE), --allow-future)

.DEFAULT_GOAL := help
.PHONY: help up down restart ps logs smoke migrate validate-seeds test-generator test-generator-db \
	load-reference generate pod-sample config clean

help:  ## List the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-18s %s\n", $$1, $$2}'

.env:
	cp .env.example .env
	@echo "Created .env from .env.example. Change the passwords before sharing the stack."

up: .env  ## Build and start the whole platform, wait until every service is healthy
	$(COMPOSE) up -d --build --wait --wait-timeout $(WAIT_TIMEOUT)
	@$(MAKE) --no-print-directory ps

down:  ## Stop the platform, keep the data
	$(COMPOSE) down

restart: down up  ## Stop and start again

ps:  ## Show services, health and URLs
	@$(COMPOSE) ps --format 'table {{.Service}}\t{{.Status}}'
	@echo ""
	@echo "  Grafana           http://localhost:3000"
	@echo "  Dagster           http://localhost:3001"
	@echo "  Redpanda Console  http://localhost:8080"
	@echo "  RustFS console    http://localhost:9001"
	@echo "  OSRM              http://localhost:5000"

logs:  ## Follow the logs of every service (make logs s=grafana for one)
	$(COMPOSE) logs -f --tail=100 $(s)

smoke: .env  ## Check that every service answers and does its job
	./scripts/smoke-test.sh

migrate: .env  ## Apply pending database migrations (make up does it too)
	$(COMPOSE) run --rm db-migrate

validate-seeds:  ## Check the AI-generated seed data: structure, consistency, geography
	$(GENERATOR) python services/generator/validate_company.py
	$(GENERATOR) python services/generator/validate_seeds.py

test-generator:  ## Run the order generator's tests (offline)
	$(GENERATOR) pytest services/generator/tests

test-generator-db: .env  ## Load the reference data and generate a past Monday twice, then check bronze with SQL
	./scripts/generator-db-test.sh $(if $(SAMPLE),--sample) $(DATE)

load-reference: .env  ## Load hub, zones, fleet, drivers, shippers, delivery notes and addresses into bronze
	set -a && . ./.env && set +a && $(GENERATOR) llobregat-generator load-reference

generate: .env  ## Generate one day of orders: make generate DATE=2026-09-28 [SEED=0] [ALLOW_FUTURE=1]
	@test -n "$(DATE)" || { echo "usage: make generate DATE=YYYY-MM-DD [SEED=0] [ALLOW_FUTURE=1]"; exit 2; }
	set -a && . ./.env && set +a && $(GENERATOR) llobregat-generator orders --date $(DATE) --seed $(SEED)$(FUTURE)

pod-sample: .env  ## Upload sample proof-of-delivery photos of a generated date: make pod-sample DATE=2026-09-28 [COUNT=20]
	@test -n "$(DATE)" || { echo "usage: make pod-sample DATE=YYYY-MM-DD [COUNT=20] [SEED=0]"; exit 2; }
	set -a && . ./.env && set +a && $(GENERATOR) llobregat-generator pod-sample --date $(DATE) --count $(COUNT) --seed $(SEED)

config: .env  ## Validate docker-compose.yml
	$(COMPOSE) config --quiet && echo "docker-compose.yml is valid"

clean:  ## Stop the platform and DELETE all data volumes (asks first)
	@read -p "This deletes every volume, including the OSRM road graph. Type yes to continue: " ans; \
	  [ "$$ans" = "yes" ] && $(COMPOSE) down -v || echo "Cancelled."
