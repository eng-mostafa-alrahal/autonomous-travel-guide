#!/usr/bin/env bash
# Production container entrypoint: apply DB migrations, then serve the API.
set -euo pipefail

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] Starting API (uvicorn) on 0.0.0.0:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS:-2}"
