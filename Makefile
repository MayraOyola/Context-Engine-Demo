BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8040
FRONTEND_PORT ?= 3040

# Active domain: reads DEMO_DOMAIN from .env automatically.
# Override with: make <target> DOMAIN=datagov
DOMAIN ?= $(or $(shell grep -s '^DEMO_DOMAIN=' .env | cut -d= -f2),datagov)

# In-place sed differs between GNU (Linux/Docker) and BSD (macOS).
SED_I := $(shell sed --version >/dev/null 2>&1 && echo "sed -i" || echo "sed -i ''")

.PHONY: help domains setup reset dev backend frontend install insight-import \
	backend-install frontend-install \
	generate-models generate-data setup-surface load-data \
	seed-memories seed-langcache seed-all flush-redis \
	validate-domain smoke-domain

help:
	@echo ""
	@echo "  make domains            Show available domains"
	@echo "  make setup [DOMAIN=X]   Full setup (first time or switch domain)"
	@echo "  make reset              Reload data for current domain"
	@echo "  make dev                Start backend + frontend"
	@echo ""
	@echo "  make install            Install Python + JS dependencies"
	@echo "  make insight-import     Write redis-insight-import.json for Redis Insight"
	@echo "  make seed-memories      Re-seed long-term memories"
	@echo "  make seed-langcache     Re-seed LangCache entries"
	@echo "  make flush-redis        Wipe Redis (preserves Agent Memory)"
	@echo ""
	@echo "  Active domain: $(DOMAIN)"
	@echo ""

domains:
	@echo ""
	@echo "Available domains:"
	@echo ""
	@for d in domains/*/domain.py; do \
		name=$$(basename $$(dirname $$d)); \
		if [ "$$name" = "$(DOMAIN)" ]; then \
			printf "  %-25s <- active\n" "$$name"; \
		else \
			printf "  %-25s\n" "$$name"; \
		fi; \
	done
	@echo ""
	@echo "Switch: make setup DOMAIN=<name>"
	@echo ""

setup:
	@if [ ! -f .env ]; then echo "No .env file. Run: cp .env.example .env"; exit 1; fi
	@echo "Setting up $(DOMAIN)..."
	@echo ""
	@$(SED_I) 's/^DEMO_DOMAIN=.*/DEMO_DOMAIN=$(DOMAIN)/' .env
	@uv run python scripts/generate_models.py --domain $(DOMAIN)
	@uv run python scripts/generate_data.py --domain $(DOMAIN)
	@uv run python scripts/flush_redis.py
	@$(SED_I) 's/^CTX_SURFACE_ID=.*/CTX_SURFACE_ID=/' .env
	@$(SED_I) 's/^MCP_AGENT_KEY=.*/MCP_AGENT_KEY=/' .env
	@uv run python scripts/setup_surface.py --domain $(DOMAIN)
	@uv run python scripts/load_data.py --domain $(DOMAIN)
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_memories
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_langcache
	@uv run python scripts/insight_import.py
	@echo ""
	@echo "Done."

reset:
	@echo "Reloading $(DOMAIN)..."
	@echo ""
	@uv run python scripts/generate_data.py --domain $(DOMAIN)
	@uv run python scripts/flush_redis.py
	@$(SED_I) 's/^CTX_SURFACE_ID=.*/CTX_SURFACE_ID=/' .env
	@$(SED_I) 's/^MCP_AGENT_KEY=.*/MCP_AGENT_KEY=/' .env
	@uv run python scripts/setup_surface.py --domain $(DOMAIN)
	@uv run python scripts/load_data.py --domain $(DOMAIN)
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_memories
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_langcache
	@uv run python scripts/insight_import.py
	@echo ""
	@echo "Done."

# --- Individual steps ---

backend-install:
	@uv sync

frontend-install:
	@cd frontend && npm install

install: backend-install frontend-install

generate-models:
	@uv run python scripts/generate_models.py --domain $(DOMAIN)

generate-data:
	@uv run python scripts/generate_data.py --domain $(DOMAIN)

load-data:
	@uv run python scripts/load_data.py --domain $(DOMAIN)

setup-surface:
	@uv run python scripts/setup_surface.py --domain $(DOMAIN)

validate-domain:
	@uv run python scripts/validate_domain.py --domain $(DOMAIN)

smoke-domain:
	@uv run python scripts/smoke_domain.py --domain $(DOMAIN)


backend:
	@uv run python -m uvicorn backend.app.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	@cd frontend && npm run dev -- --host 0.0.0.0 --port $(FRONTEND_PORT)

flush-redis:
	@uv run python scripts/flush_redis.py

insight-import:
	@uv run python scripts/insight_import.py

seed-memories:
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_memories

seed-langcache:
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_langcache

seed-all: seed-memories seed-langcache

dev:
	@lsof -ti:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@lsof -ti:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@sleep 0.5
	@trap 'kill 0' EXIT; $(MAKE) backend & $(MAKE) frontend & wait
