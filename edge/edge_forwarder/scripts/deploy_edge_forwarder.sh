#!/usr/bin/env bash
set -euo pipefail

# Edge-only deploy helper for edge-forwarder.
# Steps:
# 1) build image (edge-forwarder only)
# 2) import image to local k3s/containerd runtime
# 3) apply edge-forwarder manifest
# 4) set image + wait rollout

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORWARDER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FORWARDER_DIR}/../.." && pwd)"

DOCKERFILE="${FORWARDER_DIR}/docker/Dockerfile.app"
CONTEXT_DIR="${REPO_ROOT}"
NAMESPACE_MANIFEST="${REPO_ROOT}/edge/deployments/00-edge-namespace.yaml"
MANIFEST="${FORWARDER_DIR}/deployments/30-edge-forwarder.yaml"

IMAGE_REPO="netops-edge-forwarder"
IMAGE_TAG="0.1"
ROLLOUT_TIMEOUT="180s"
BUILD_IMAGE=1
IMPORT_IMAGE=1
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  deploy_edge_forwarder.sh [options]

Options:
  --tag TAG             Image tag (default: 0.1)
  --repo NAME           Image repo (default: netops-edge-forwarder)
  --timeout DURATION    Rollout timeout (default: 180s)
  --skip-build          Skip image build
  --skip-import         Skip import to k3s runtime
  --dry-run             Print commands only
  -h, --help            Show help

Examples:
  edge/edge_forwarder/scripts/deploy_edge_forwarder.sh
  edge/edge_forwarder/scripts/deploy_edge_forwarder.sh --tag 0.2
  edge/edge_forwarder/scripts/deploy_edge_forwarder.sh --skip-build --skip-import
USAGE
}

log() {
  printf '[deploy-edge-forwarder] %s\n' "$*"
}

run_cmd() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
  fi
}

detect_builder() {
  if command -v docker >/dev/null 2>&1; then
    echo "docker"
    return
  fi
  if command -v nerdctl >/dev/null 2>&1; then
    echo "nerdctl"
    return
  fi
  echo ""
}

import_image_to_runtime() {
  local image_ref="$1"
  local tmp_tar
  tmp_tar="$(mktemp "/tmp/${image_ref//[:\/]/_}.XXXXXX.tar")"

  if command -v docker >/dev/null 2>&1; then
    run_cmd "docker save -o '${tmp_tar}' '${image_ref}'"
  elif command -v nerdctl >/dev/null 2>&1; then
    run_cmd "nerdctl save -o '${tmp_tar}' '${image_ref}'"
  else
    log "ERROR: no docker/nerdctl found for image save"
    exit 1
  fi

  if command -v k3s >/dev/null 2>&1; then
    run_cmd "k3s ctr images import '${tmp_tar}'"
  elif command -v ctr >/dev/null 2>&1; then
    run_cmd "ctr -n k8s.io images import '${tmp_tar}'"
  else
    log "ERROR: neither k3s nor ctr found"
    rm -f "${tmp_tar}"
    exit 1
  fi

  rm -f "${tmp_tar}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      IMAGE_TAG="$2"
      shift 2
      ;;
    --repo)
      IMAGE_REPO="$2"
      shift 2
      ;;
    --timeout)
      ROLLOUT_TIMEOUT="$2"
      shift 2
      ;;
    --skip-build)
      BUILD_IMAGE=0
      shift
      ;;
    --skip-import)
      IMPORT_IMAGE=0
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log "ERROR: unknown option '$1'"
      usage
      exit 2
      ;;
  esac
done

IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

if [[ ! -f "${DOCKERFILE}" ]]; then
  log "ERROR: Dockerfile not found: ${DOCKERFILE}"
  exit 2
fi
if [[ ! -f "${NAMESPACE_MANIFEST}" ]]; then
  log "ERROR: Namespace manifest not found: ${NAMESPACE_MANIFEST}"
  exit 2
fi
if [[ ! -f "${MANIFEST}" ]]; then
  log "ERROR: Manifest not found: ${MANIFEST}"
  exit 2
fi
if ! command -v kubectl >/dev/null 2>&1; then
  log "ERROR: kubectl not found"
  exit 2
fi

BUILDER="$(detect_builder)"
if [[ "${BUILD_IMAGE}" -eq 1 && -z "${BUILDER}" ]]; then
  log "ERROR: no docker/nerdctl found"
  exit 2
fi

log "repo root: ${REPO_ROOT}"
log "forwarder dir: ${FORWARDER_DIR}"
log "image: ${IMAGE}"
log "build=${BUILD_IMAGE}, import=${IMPORT_IMAGE}"

if [[ "${BUILD_IMAGE}" -eq 1 ]]; then
  log "building image via ${BUILDER}"
  run_cmd "${BUILDER} build -t '${IMAGE}' -f '${DOCKERFILE}' '${CONTEXT_DIR}'"
fi

if [[ "${IMPORT_IMAGE}" -eq 1 ]]; then
  log "importing image to runtime"
  import_image_to_runtime "${IMAGE}"
fi

log "applying namespace manifest"
run_cmd "kubectl apply -f '${NAMESPACE_MANIFEST}'"

log "applying deployment manifest"
run_cmd "kubectl apply -f '${MANIFEST}'"

log "set deployment image"
run_cmd "kubectl -n edge set image deployment/edge-forwarder edge-forwarder='${IMAGE}'"

log "waiting rollout"
run_cmd "kubectl -n edge rollout status deployment/edge-forwarder --timeout='${ROLLOUT_TIMEOUT}'"

if [[ "${DRY_RUN}" -eq 0 ]]; then
  log "status:"
  kubectl -n edge get deploy edge-forwarder -o wide || true
  kubectl -n edge get pods -l app=edge-forwarder -o wide || true
fi

log "done"
