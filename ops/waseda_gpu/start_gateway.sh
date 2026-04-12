#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${NETOPS_LLM_BASE_DIR:-$HOME/netops-llm}"
LOG_DIR="$BASE_DIR/logs"
PID_FILE="$BASE_DIR/runtime/netops-llm-gateway.pid"

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"

export NETOPS_GATEWAY_HOST="${NETOPS_GATEWAY_HOST:-127.0.0.1}"
export NETOPS_GATEWAY_PORT="${NETOPS_GATEWAY_PORT:-18080}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://127.0.0.1:8000/v1}"
export OPENAI_MODEL="${OPENAI_MODEL:-glm-fast}"
export OPENAI_MAX_TOKENS="${OPENAI_MAX_TOKENS:-1536}"
export OPENAI_TEMPERATURE="${OPENAI_TEMPERATURE:-0.2}"
export OPENAI_TIMEOUT_SEC="${OPENAI_TIMEOUT_SEC:-90}"

LOG_FILE="$LOG_DIR/netops-llm-gateway.$(date -u +%Y%m%dT%H%M%SZ).log"
nohup python3 "$SCRIPT_DIR/netops_llm_gateway.py" >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"
echo "pid=$(cat "$PID_FILE")"
echo "log=$LOG_FILE"
echo "health=http://$NETOPS_GATEWAY_HOST:$NETOPS_GATEWAY_PORT/healthz"
