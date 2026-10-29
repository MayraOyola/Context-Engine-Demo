BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8040
FRONTEND_PORT ?= 3040

# The domain pack to run (one ships in domains/). Read from .env, override with DOMAIN=<name>.
DOMAIN ?= $(or $(shell grep -s '^DEMO_DOMAIN=' .env | cut -d= -f2),datagov)

# In-place sed differs between GNU (Linux) and BSD (macOS).
SED_I := $(shell sed --version >/dev/null 2>&1 && echo "sed -i" || echo "sed -i ''")

.PHONY: help install setup reset load dev backend frontend seed-memories seed-langcache flush-redis insight-import

help:
	@echo ""
	@echo "  make install          Install Python and JS dependencies"
	@echo "  make setup            First-time setup: generate models, then load everything into Redis"
	@echo "  make reset            Reload data, memories and cache (wipes the Redis database)"
	@echo "  make dev              Start backend ($(BACKEND_PORT)) and frontend ($(FRONTEND_PORT))"
	@echo ""
	@echo "  make seed-memories    Re-seed each demo user's long-term memories"
	@echo "  make seed-langcache   Re-seed the semantic cache"
	@echo "  make flush-redis      Wipe the Redis database (Agent Memory is untouched)"
	@echo "  make insight-import   Write redis-insight-import.json for Redis Insight"
	@echo ""

install:
	@uv sync
	@cd frontend && npm install

setup:
	@if [ ! -f .env ]; then echo "No .env file. Run: cp .env.example .env"; exit 1; fi
	@$(SED_I) 's/^DEMO_DOMAIN=.*/DEMO_DOMAIN=$(DOMAIN)/' .env
	@uv run python scripts/generate_models.py --domain $(DOMAIN)
	@$(MAKE) --no-print-directory load

reset: load

# Generate data, flush Redis, create the Context Retriever surface, load the data, seed memory and cache.
load:
	@uv run python scripts/generate_data.py --domain $(DOMAIN)
	@uv run python scripts/flush_redis.py
	@$(SED_I) 's/^CTX_SURFACE_ID=.*/CTX_SURFACE_ID=/' .env
	@$(SED_I) 's/^MCP_AGENT_KEY=.*/MCP_AGENT_KEY=/' .env
	@uv run python scripts/setup_surface.py --domain $(DOMAIN)
	@uv run python scripts/load_data.py --domain $(DOMAIN)
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_memories
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_langcache
	@uv run python scripts/insight_import.py
	@echo "Done."

seed-memories:
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_memories

seed-langcache:
	@DEMO_DOMAIN=$(DOMAIN) uv run python -m scripts.seed_langcache

flush-redis:
	@uv run python scripts/flush_redis.py

insight-import:
	@uv run python scripts/insight_import.py

backend:
	@uv run python -m uvicorn backend.app.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	@cd frontend && npm run dev -- --host 0.0.0.0 --port $(FRONTEND_PORT)

dev:
	@lsof -ti:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@lsof -ti:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@sleep 0.5
	@trap 'kill 0' EXIT; $(MAKE) backend & $(MAKE) frontend & wait
