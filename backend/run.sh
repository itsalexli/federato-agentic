#!/usr/bin/env bash
# Start the API on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn app.main:app --reload --port 8000 --app-dir backend
