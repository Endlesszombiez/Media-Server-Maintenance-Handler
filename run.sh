#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BIN="${ROOT_DIR}/.venv/bin/media-sm"

if [[ ! -x "${APP_BIN}" ]]; then
  echo "App is not installed yet. Running install.sh first..."
  "${ROOT_DIR}/install.sh"
fi

exec "${APP_BIN}" "$@"
