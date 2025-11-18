#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v poetry >/dev/null 2>&1; then
  cat <<'MSG'
Poetry is required to start flash-green-poc.
Install it with pipx (`pipx install poetry`) or follow https://python-poetry.org/docs/#installation,
then re-run this starter.
MSG
  exit 1
fi

echo "Updating repository at $REPO_ROOT..."
git pull --rebase

echo "Installing/updating Python dependencies with Poetry..."
poetry install

ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
REQUIRED_VARS=("API_KEY")

if [[ "${PREFLIGHT:-1}" == "1" ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing environment file: $ENV_FILE"
    echo "Copy env.staging.example or env.production.example to .env and fill in required values first."
    exit 1
  fi

  missing_vars=()
  while IFS= read -r var_name; do
    missing_vars+=("$var_name")
  done < <(for var in "${REQUIRED_VARS[@]}"; do
    if ! grep -Eq "^[[:space:]]*${var}=" "$ENV_FILE"; then
      echo "$var"
    fi
  done)

  if (( ${#missing_vars[@]} )); then
    echo "The following required settings are missing in $ENV_FILE: ${missing_vars[*]}"
    echo "Populate them before starting the API/UI server."
    exit 1
  fi
fi

echo "Loading environment from $ENV_FILE..."
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"
mkdir -p "$LOG_DIR"
UVICORN_LOG="$LOG_DIR/uvicorn_macos.log"

if pgrep -f "uvicorn app.web:api" >/dev/null 2>&1; then
  echo "A uvicorn process for app.web:api is already running. Check $UVICORN_LOG if this is unexpected."
else
  echo "Starting uvicorn (logs: $UVICORN_LOG)..."
  nohup poetry run uvicorn app.web:api --host 0.0.0.0 --port 8000 >"$UVICORN_LOG" 2>&1 &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$LOG_DIR/uvicorn.pid"
  echo "Started uvicorn with PID $SERVER_PID"
fi

UI_URL="${UI_URL:-http://localhost:8000/ui}"

if command -v curl >/dev/null 2>&1; then
  for attempt in {1..12}; do
    if curl -fs --max-time 2 "$UI_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

echo "Opening $UI_URL in your browser..."
if command -v open >/dev/null 2>&1 && open "$UI_URL" >/dev/null 2>&1; then
  echo "macOS launch successful via 'open'."
elif command -v python3 >/dev/null 2>&1 && python3 - <<PY
import sys
import webbrowser

url = "$UI_URL"
if not webbrowser.open(url, new=2):
    sys.exit(1)
PY
then
  echo "Opened $UI_URL using Python's webbrowser module."
else
  echo "Please open $UI_URL manually if it did not appear automatically."
fi
