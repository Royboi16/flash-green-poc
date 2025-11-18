#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/preflight_check.py

alembic upgrade head

exec python -m app.orchestrator
