#!/usr/bin/env bash
#
# Start just the FastAPI backend.
#
#   ./backend.sh
#
# For both the backend and the frontend dev server together, use ./dev.sh
# instead. Manual equivalents are in the README.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
API_HOST="${AGENT_KIT_HOST:-127.0.0.1}"
API_PORT="${AGENT_KIT_PORT:-8000}"

if [ -t 1 ]; then
  C_ERR=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'
else
  C_ERR=''; C_OK=''; C_OFF=''
fi

die() { printf '%s\n' "${C_ERR}$*${C_OFF}" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------

if [ ! -d "$VENV" ]; then
  die "No Python virtualenv found at .venv/

The backend runs from this project's own virtualenv. Create it with:

    python3 -m venv .venv
    .venv/bin/pip install -e \".[dev]\"

then run ./backend.sh again."
fi

if [ ! -x "$VENV/bin/python" ]; then
  die "'.venv' exists but has no usable Python at .venv/bin/python.

It may be a partially created or non-standard virtualenv. Remove it and rebuild:

    rm -rf .venv
    python3 -m venv .venv
    .venv/bin/pip install -e \".[dev]\""
fi

if ! "$VENV/bin/python" -c 'import uvicorn, fastapi' 2>/dev/null; then
  die "The virtualenv is missing the backend's dependencies (fastapi/uvicorn).

Install the project into it with:

    .venv/bin/pip install -e \".[dev]\""
fi

# --- run ---------------------------------------------------------------------

printf '%s\n' "${C_OK}agent-kit backend${C_OFF}  http://${API_HOST}:${API_PORT}"

cd "$ROOT" || exit 1
exec "$VENV/bin/python" -m uvicorn agent_kit.playground.app:app \
  --host "$API_HOST" --port "$API_PORT" --reload
