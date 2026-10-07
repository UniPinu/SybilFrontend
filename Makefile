.PHONY: help setup weights candidates pool dev dev-backend dev-frontend build test test-fast test-slow lint clean clean-cache

BACKEND := backend
FRONTEND := frontend
POOL ?= 16
REFERENCE ?= 12

help:
	@echo "setup       install everything (uv sync, pnpm install) and check the install"
	@echo "weights     download Sybil's checkpoints and verify against published scores"
	@echo "candidates  build data/candidates.parquet from the IDC index (no scans)"
	@echo "pool        prepare the curated pool + reference sample (POOL=16 REFERENCE=12)"
	@echo "dev         run uvicorn :8000 and vite :5173 together"
	@echo "build       build the frontend into frontend/dist (served by the backend)"
	@echo "test        smoke test + unit tests"
	@echo "clean-cache drop processed patients (keeps the model weights)"

setup:
	cd $(BACKEND) && uv sync --extra dev
	cd $(FRONTEND) && pnpm install
	$(MAKE) weights
	$(MAKE) candidates

weights:
	cd $(BACKEND) && uv run python scripts/smoke_test.py

candidates:
	cd $(BACKEND) && uv run python scripts/build_candidates.py

pool:
	cd $(BACKEND) && uv run python scripts/prepare_pool.py --pool $(POOL) --reference $(REFERENCE)

dev-backend:
	cd $(BACKEND) && uv run uvicorn app.main:app --port 8000 --reload

dev-frontend:
	cd $(FRONTEND) && pnpm dev

# One terminal, both servers; Ctrl-C stops both.
dev:
	$(MAKE) -j2 dev-backend dev-frontend

build:
	cd $(FRONTEND) && pnpm build

test: test-fast
	cd $(BACKEND) && uv run python scripts/smoke_test.py --compare-runner

test-fast:
	cd $(BACKEND) && uv run pytest -m "not slow"

test-slow:
	cd $(BACKEND) && uv run pytest -m slow

lint:
	cd $(FRONTEND) && pnpm lint

clean-cache:
	cd $(BACKEND) && uv run python -c "import shutil; from app.config import settings; shutil.rmtree(settings.cache_dir, ignore_errors=True); print('cache cleared')"

clean: clean-cache
	rm -rf $(FRONTEND)/dist $(BACKEND)/.venv
