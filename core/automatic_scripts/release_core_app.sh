#!/usr/bin/env bash
set -euo pipefail

# One-shot release helper for core components on core node (r450).
# This script intentionally does NOT manage edge components.

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

echo "[1/6] Building image ${IMAGE}"
docker build -t "$IMAGE" -f core/docker/Dockerfile.app .

echo "[2/6] Saving tar to ${TAR_PATH}"
docker save "$IMAGE" -o "$TAR_PATH"

echo "[3/6] Importing image on local node (r450)"
$LOCAL_IMPORT_CMD "$TAR_PATH"

echo "[4/6] Updating core-correlator image to ${IMAGE}"
kubectl -n netops-core set image deployment/core-correlator core-correlator="$IMAGE"

echo "[5/6] Updating core-alerts-sink image to ${IMAGE}"
kubectl -n netops-core set image deployment/core-alerts-sink core-alerts-sink="$IMAGE"

echo "[6/6] Waiting rollout"
kubectl -n netops-core rollout status deployment/core-correlator
kubectl -n netops-core rollout status deployment/core-alerts-sink

echo "Done. Released core image: ${IMAGE} (core-correlator + core-alerts-sink)"
