#!/bin/sh
set -eu

APP_CONFIG="${HOUSING_MONITOR_CONFIG:-/app/config.yaml}"

mkdir -p /app/data /app/exports /app/artifacts

has_config_flag() {
  for arg in "$@"; do
    if [ "$arg" = "--config" ]; then
      return 0
    fi
  done
  return 1
}

case "${1:-}" in
  "")
    set -- run
    ;;
  sh|bash|/bin/sh|/bin/bash|python|python3)
    exec "$@"
    ;;
esac

case "$1" in
  run|poll-once|test-adapter|recent-matches|export|list-sources|init)
    if ! has_config_flag "$@"; then
      set -- "$@" --config "$APP_CONFIG"
    fi
    if [ "$1" != "init" ] && [ ! -f "$APP_CONFIG" ]; then
      echo "Config file not found at $APP_CONFIG" >&2
      echo "Mount ./config.yaml to /app/config.yaml or set HOUSING_MONITOR_CONFIG." >&2
      exit 1
    fi
    exec xvfb-run -a housing-monitor "$@"
    ;;
  *)
    exec xvfb-run -a housing-monitor "$@"
    ;;
esac
