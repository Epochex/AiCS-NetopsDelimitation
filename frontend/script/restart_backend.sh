#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${BACKEND_SERVICE:-netops-ops-console-backend.service}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8026}"
BACKEND_CMD=(
  "${ROOT_DIR}/.venv/bin/uvicorn"
  "gateway.app.main:app"
  "--app-dir" "${ROOT_DIR}"
  "--host" "${BACKEND_HOST}"
  "--port" "${BACKEND_PORT}"
)
LOG_PATH="${BACKEND_LOG_PATH:-/tmp/netops-ops-console-backend.log}"
PID_PATH="${BACKEND_PID_PATH:-/tmp/netops-ops-console-backend.pid}"

run_cmd() {
  if [[ "${EUID}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

have_systemd() {
  systemctl show-environment >/dev/null 2>&1
}

stop_manual_backend() {
  if [[ -f "${PID_PATH}" ]]; then
    local old_pid
    old_pid="$(cat "${PID_PATH}")"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" >/dev/null 2>&1; then
      kill "${old_pid}" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "${old_pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${PID_PATH}"
  fi

  pkill -f "${ROOT_DIR}/.venv/bin/uvicorn .*gateway.app.main:app.*--port ${BACKEND_PORT}" >/dev/null 2>&1 || true
}

start_manual_backend() {
  echo "[info] starting backend manually on ${BACKEND_HOST}:${BACKEND_PORT}"
  (
    cd "${ROOT_DIR}"
    export PYTHONUNBUFFERED=1
    export NETOPS_RUNTIME_ROOT="${NETOPS_RUNTIME_ROOT:-/data/netops-runtime}"
    export NETOPS_CONSOLE_REPO_ROOT="${NETOPS_CONSOLE_REPO_ROOT:-/data/Netops-causality-remediation}"
    export NETOPS_CONSOLE_FRONTEND_DIST="${NETOPS_CONSOLE_FRONTEND_DIST:-${ROOT_DIR}/dist}"
    nohup "${BACKEND_CMD[@]}" >"${LOG_PATH}" 2>&1 &
    echo $! >"${PID_PATH}"
  )
  sleep 2
  curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/healthz" >/dev/null
  echo "[info] manual backend pid: $(cat "${PID_PATH}")"
  echo "[info] backend log: ${LOG_PATH}"
}

echo "[info] restarting backend service: ${SERVICE_NAME}"
if have_systemd; then
  run_cmd systemctl restart "${SERVICE_NAME}"
  echo "[info] service state:"
  run_cmd systemctl is-active "${SERVICE_NAME}"
  echo "[info] service status:"
  run_cmd systemctl status "${SERVICE_NAME}" --no-pager | sed -n '1,20p'
else
  echo "[warn] systemd bus unavailable, falling back to manual uvicorn restart"
  stop_manual_backend
  start_manual_backend
fi
