#!/usr/bin/env bash
set -euo pipefail

# One-shot release helper for core-correlator on core node (r450).
# This script intentionally does not manage edge components.

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

APP_NAME="netops-core-app"
TAG_DEFAULT="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
TAG="${1:-$TAG_DEFAULT}"
LOCAL_IMPORT_CMD="k3s ctr images import"
TAR_PATH="/tmp/${APP_NAME}_${TAG}.tar"
IMAGE="${APP_NAME}:${TAG}"

usage() {
  cat <<EOF
Usage:
  ./core/automatic_scripts/release_core_app.sh [tag]

Examples:
  ./core/automatic_scripts/release_core_app.sh
  ./core/automatic_scripts/release_core_app.sh v20260303
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker not found. Please install docker first." >&2
  exit 1
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "[ERROR] kubectl not found." >&2
  exit 1
fi

echo "[1/5] Building image ${IMAGE}"
docker build -t "$IMAGE" -f core/docker/Dockerfile.app .

echo "[2/5] Saving tar to ${TAR_PATH}"
docker save "$IMAGE" -o "$TAR_PATH"

echo "[3/5] Importing image on local node (r450)"
$LOCAL_IMPORT_CMD "$TAR_PATH"

echo "[4/7] Copying tar to edge node ${EDGE_USER}@${EDGE_HOST}"
scp "$TAR_PATH" "${EDGE_USER}@${EDGE_HOST}:${TAR_PATH}"

echo "[5/7] Importing image on edge node (r230)"
ssh "${EDGE_USER}@${EDGE_HOST}" "$REMOTE_IMPORT_CMD ${TAR_PATH}"

if [[ "$TARGET" == "all" || "$TARGET" == "edge" ]]; then
  echo "[6/7] Updating edge-forwarder image to ${IMAGE}"
  kubectl -n edge set image deployment/edge-forwarder edge-forwarder="$IMAGE"
fi
if [[ "$TARGET" == "all" || "$TARGET" == "core" ]]; then
  echo "[6/7] Updating core-correlator image to ${IMAGE}"
  kubectl -n netops-core set image deployment/core-correlator core-correlator="$IMAGE"
  echo "[6/7] Updating core-alerts-sink image to ${IMAGE}"
  kubectl -n netops-core set image deployment/core-alerts-sink core-alerts-sink="$IMAGE"
fi

echo "[7/7] Waiting rollout"
if [[ "$TARGET" == "all" || "$TARGET" == "edge" ]]; then
  kubectl -n edge rollout status deployment/edge-forwarder
fi
if [[ "$TARGET" == "all" || "$TARGET" == "core" ]]; then
  kubectl -n netops-core rollout status deployment/core-correlator
  kubectl -n netops-core rollout status deployment/core-alerts-sink
fi

echo "Done. Released core image: ${IMAGE}"
