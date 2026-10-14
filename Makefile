.PHONY: help check setup weights candidates pool dev dev-backend dev-frontend build test test-fast test-slow lint clean clean-cache static upload-static visualiser

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
	@echo "test-fast   unit tests only (no model, no network)"
	@echo "test-slow   the real-ensemble tests (several minutes)"
	@echo "lint        lint the frontend"
	@echo "clean-cache drop processed patients (keeps the model weights)"
	@echo "visualiser  record one real run step by step for the Visualiser page (~25 min)"
	@echo "static      snapshot cached results into backend/static_export (read-only deploy)"
	@echo "upload-static  sync that snapshot to R2 with rclone (R2_BUCKET=..., RCLONE_REMOTE=r2)"

# Fail early, with a useful message, instead of deep inside uv or pnpm.
check:
	@if [ "$$(uname -s)" = "Darwin" ] && [ "$$(uname -m)" != "arm64" ]; then \n		echo "Intel Macs are not supported: Sybil's torch pin has no Intel-mac wheel (see README, Platforms)."; exit 1; fi
	@command -v uv >/dev/null || { echo "uv not found. macOS: brew install uv"; exit 1; }
	@command -v node >/dev/null || { echo "node not found. macOS: brew install node"; exit 1; }
	@command -v pnpm >/dev/null || { echo "pnpm not found. Run: corepack enable pnpm  (or brew install pnpm)"; exit 1; }

setup: check
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

# Downloads one scan, runs the ensemble with hooks, writes frontend/public/visualiser/<case>/.
CASE ?= 217203_T2
visualiser:
	cd $(BACKEND) && uv run python scripts/capture_visualiser.py --case $(CASE)

# --- read-only deploy: cached results as static files (see README) ----------
RCLONE_REMOTE ?= r2
R2_BUCKET ?=

static:
	cd $(BACKEND) && uv run python scripts/export_static.py

# Images never change once rendered; JSON may be re-exported, so keep it short-lived.
upload-static:
	@test -n "$(R2_BUCKET)" || { echo "Set R2_BUCKET, e.g. make upload-static R2_BUCKET=sybil-results"; exit 1; }
	@command -v rclone >/dev/null || { echo "rclone not found. macOS: brew install rclone"; exit 1; }
	rclone copy $(BACKEND)/static_export $(RCLONE_REMOTE):$(R2_BUCKET) --include "*.webp" \
		--header-upload "Cache-Control: public, max-age=31536000, immutable" --transfers 32 --progress
	rclone copy $(BACKEND)/static_export $(RCLONE_REMOTE):$(R2_BUCKET) --exclude "*.webp" \
		--header-upload "Cache-Control: public, max-age=300" --transfers 32 --progress

clean-cache:
	cd $(BACKEND) && uv run python -c "import shutil; from app.config import settings; shutil.rmtree(settings.cache_dir, ignore_errors=True); print('cache cleared')"

clean: clean-cache
	rm -rf $(FRONTEND)/dist $(BACKEND)/.venv
