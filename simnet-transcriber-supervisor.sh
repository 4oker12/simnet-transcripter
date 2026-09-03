#!/bin/bash
set -euo pipefail

ROOT="${SIMNET_TRANSCRIBER_DIR:-/workspace/simnet-transcripter}"
PYTHON_BIN="${SIMNET_PYTHON:-/venv/main/bin/python}"
HOST="${SIMNET_HOST:-127.0.0.1}"
PORT="${SIMNET_PORT:-8000}"

if [[ -r /opt/supervisor-scripts/utils/logging.sh ]]; then
  # Vast images provide these helpers, but the service must remain runnable
  # without them on another host.
  . /opt/supervisor-scripts/utils/logging.sh
fi
if [[ -r /opt/supervisor-scripts/utils/environment.sh ]]; then
  . /opt/supervisor-scripts/utils/environment.sh
fi

[[ -d "$ROOT" ]] || { echo "Transcriber directory not found: $ROOT" >&2; exit 1; }
[[ -x "$PYTHON_BIN" ]] || { echo "Python not executable: $PYTHON_BIN" >&2; exit 1; }

cd "$ROOT"
exec "$PYTHON_BIN" -m uvicorn app:app --host "$HOST" --port "$PORT"
