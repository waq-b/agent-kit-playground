#!/usr/bin/env bash
#
# Start the FastAPI backend and the React dev server together.
#
#   ./dev.sh
#
# Output from both processes is prefixed and colour-coded. Ctrl-C stops both.
# Manual equivalents are in the README if you'd rather run them separately.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
FRONTEND="$ROOT/frontend"
API_HOST="${AGENT_KIT_HOST:-127.0.0.1}"
API_PORT="${AGENT_KIT_PORT:-8000}"

if [ -t 1 ]; then
  C_API=$'\033[36m'; C_WEB=$'\033[35m'; C_ERR=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'
else
  C_API=''; C_WEB=''; C_ERR=''; C_OK=''; C_OFF=''
fi

die() { printf '%s\n' "${C_ERR}$*${C_OFF}" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------

if [ ! -d "$VENV" ]; then
  die "No Python virtualenv found at .venv/

The backend runs from this project's own virtualenv. Create it with:

    python3 -m venv .venv
    .venv/bin/pip install -e \".[dev]\"

then run ./dev.sh again."
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

if [ ! -d "$FRONTEND/node_modules" ]; then
  die "Frontend dependencies are not installed.

Install them with:

    cd frontend && npm install

then run ./dev.sh again."
fi

# --- run ---------------------------------------------------------------------

pids=()

cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
  printf '\n%s\n' "${C_OK}Both processes stopped.${C_OFF}"
}
trap cleanup INT TERM EXIT

# `sed -u` (GNU) and `sed -l` (BSD) both mean "line buffered", and neither
# exists on the other. Fall back to plain sed if the flag isn't supported.
prefix() {
  local label="$1"
  if sed -u '' </dev/null >/dev/null 2>&1; then
    sed -u "s/^/${label}/"
  elif sed -l '' </dev/null >/dev/null 2>&1; then
    sed -l "s/^/${label}/"
  else
    sed "s/^/${label}/"
  fi
}

printf '%s\n' "${C_OK}agent-kit playground${C_OFF}"
printf '  %sapi%s  http://%s:%s\n' "$C_API" "$C_OFF" "$API_HOST" "$API_PORT"
printf '  %sweb%s  http://localhost:5173\n\n' "$C_WEB" "$C_OFF"

(
  cd "$ROOT" || exit 1
  exec "$VENV/bin/python" -m uvicorn agent_kit.playground.app:app \
    --host "$API_HOST" --port "$API_PORT" --reload
) 2>&1 | prefix "${C_API}[api]${C_OFF} " &
pids+=($!)

(
  cd "$FRONTEND" || exit 1
  # Point Vite's proxy at whatever host/port the backend actually got.
  AGENT_KIT_API="http://${API_HOST}:${API_PORT}" exec npm run dev --silent
) 2>&1 | prefix "${C_WEB}[web]${C_OFF} " &
pids+=($!)

wait -n 2>/dev/null || wait
printf '%s\n' "${C_ERR}One process exited — shutting the other down.${C_OFF}" >&2
