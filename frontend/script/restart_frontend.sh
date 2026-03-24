#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}"
WEB_SERVICE="${FRONTEND_WEB_SERVICE:-nginx.service}"
NODE_BIN="${NODE_BIN:-/data/.local/node/bin}"

run_cmd() {
  if [[ "${EUID}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

echo "[info] building frontend in ${FRONTEND_DIR}"
cd "${FRONTEND_DIR}"
PATH="${NODE_BIN}:$PATH" npm run build

echo "[info] validating nginx config"
run_cmd nginx -t

echo "[info] reloading web service: ${WEB_SERVICE}"
run_cmd systemctl reload "${WEB_SERVICE}"
echo "[info] service state:"
run_cmd systemctl is-active "${WEB_SERVICE}"
