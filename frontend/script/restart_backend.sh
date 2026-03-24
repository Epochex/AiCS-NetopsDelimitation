#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${BACKEND_SERVICE:-netops-ops-console-backend.service}"

run_cmd() {
  if [[ "${EUID}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

echo "[info] restarting backend service: ${SERVICE_NAME}"
run_cmd systemctl restart "${SERVICE_NAME}"
echo "[info] service state:"
run_cmd systemctl is-active "${SERVICE_NAME}"
echo "[info] service status:"
run_cmd systemctl status "${SERVICE_NAME}" --no-pager | sed -n '1,20p'
