#!/usr/bin/env bash
set -euo pipefail

SSH_HOST="${WASEDA_GPU_SSH_HOST:-waseda-gpu}"
LOCAL_HOST="${LOCAL_HOST:-127.0.0.1}"
LOCAL_PORT="${LOCAL_PORT:-18080}"
REMOTE_HOST="${REMOTE_HOST:-127.0.0.1}"
REMOTE_PORT="${REMOTE_PORT:-18080}"

echo "opening tunnel: http://$LOCAL_HOST:$LOCAL_PORT -> $SSH_HOST:$REMOTE_HOST:$REMOTE_PORT"
exec ssh \
  -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -L "$LOCAL_HOST:$LOCAL_PORT:$REMOTE_HOST:$REMOTE_PORT" \
  "$SSH_HOST"
