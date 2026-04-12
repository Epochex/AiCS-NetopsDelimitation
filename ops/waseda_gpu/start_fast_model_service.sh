#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${NETOPS_LLM_BASE_DIR:-$HOME/netops-llm}"
MODEL_PATH="${MODEL_PATH:-$HOME/models/GLM-4.7-Flash}"
HOST="${MODEL_HOST:-127.0.0.1}"
PORT="${MODEL_PORT:-8000}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-glm-fast}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.82}"
MIN_FREE_MB="${MIN_FREE_MB:-22000}"
MAX_UTIL_PERCENT="${MAX_UTIL_PERCENT:-25}"
GPU_COUNT="${GPU_COUNT:-1}"
LOCK_FILE="${LOCK_FILE:-$BASE_DIR/runtime/netops-llm-a6000.lock.json}"
LOG_DIR="$BASE_DIR/logs"
PID_FILE="$BASE_DIR/runtime/vllm.pid"

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"

if [[ -z "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  eval "$(
    python3 "$SCRIPT_DIR/select_a6000_gpu.py" \
      --count "$GPU_COUNT" \
      --min-free-mb "$MIN_FREE_MB" \
      --max-util-percent "$MAX_UTIL_PERCENT" \
      --allow-busy \
      --write-lock "$LOCK_FILE" \
      --emit shell
  )"
fi

LOG_FILE="$LOG_DIR/vllm.$(date -u +%Y%m%dT%H%M%SZ).log"
echo "starting vLLM model service"
echo "model=$MODEL_PATH"
echo "served_model_name=$SERVED_MODEL_NAME"
echo "cuda_visible_devices=$CUDA_VISIBLE_DEVICES"
echo "log=$LOG_FILE"

if command -v vllm >/dev/null 2>&1; then
  nohup vllm serve "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --trust-remote-code \
    >"$LOG_FILE" 2>&1 &
else
  nohup python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --trust-remote-code \
    >"$LOG_FILE" 2>&1 &
fi

echo "$!" > "$PID_FILE"
echo "pid=$(cat "$PID_FILE")"
echo "health=http://$HOST:$PORT/health"
