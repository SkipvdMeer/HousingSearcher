#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "${ROOT_DIR}/compose.yaml")

usage() {
  cat <<'EOF'
Usage: ./scripts/container.sh <command> [args...]

Commands:
  deploy      Build and start the container in detached mode
  start       Start the existing service
  stop        Stop the service
  restart     Restart the service
  status      Show compose service status
  logs        Follow container logs
  poll-once   Run a one-off poll inside the container
  shell       Open a shell in the running container
  down        Stop and remove the compose stack
EOF
}

ensure_runtime_files() {
  mkdir -p "${ROOT_DIR}/data" "${ROOT_DIR}/exports" "${ROOT_DIR}/artifacts"
  if [[ ! -f "${ROOT_DIR}/config.yaml" ]]; then
    cp "${ROOT_DIR}/config.vps.example.yaml" "${ROOT_DIR}/config.yaml"
    echo "Created ${ROOT_DIR}/config.yaml from config.vps.example.yaml"
    echo "Review the config before running a real deploy."
  fi
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

case "$1" in
  deploy)
    shift
    ensure_runtime_files
    "${COMPOSE[@]}" up -d --build "$@"
    ;;
  start)
    shift
    ensure_runtime_files
    "${COMPOSE[@]}" up -d "$@"
    ;;
  stop)
    shift
    "${COMPOSE[@]}" stop "$@"
    ;;
  restart)
    shift
    "${COMPOSE[@]}" restart "$@"
    ;;
  status)
    shift
    "${COMPOSE[@]}" ps "$@"
    ;;
  logs)
    shift
    "${COMPOSE[@]}" logs -f --tail=200 "$@"
    ;;
  poll-once)
    shift
    ensure_runtime_files
    "${COMPOSE[@]}" run --rm housing-monitor poll-once "$@"
    ;;
  shell)
    shift
    "${COMPOSE[@]}" exec housing-monitor sh "$@"
    ;;
  down)
    shift
    "${COMPOSE[@]}" down "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
