# Llobregat Express · common commands. Run `make` to list them.

COMPOSE := docker compose
WAIT_TIMEOUT ?= 1800

.DEFAULT_GOAL := help
.PHONY: help up down restart ps logs smoke migrate validate-seeds config clean

help:  ## List the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-15s %s\n", $$1, $$2}'

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
	uv run --with jsonschema python services/generator/validate_company.py

config: .env  ## Validate docker-compose.yml
	$(COMPOSE) config --quiet && echo "docker-compose.yml is valid"

clean:  ## Stop the platform and DELETE all data volumes (asks first)
	@read -p "This deletes every volume, including the OSRM road graph. Type yes to continue: " ans; \
	  [ "$$ans" = "yes" ] && $(COMPOSE) down -v || echo "Cancelled."
