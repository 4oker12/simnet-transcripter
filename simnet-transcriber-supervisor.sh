#!/bin/bash
set -euo pipefail

ROOT=/workspace/simnet-transcriber
if [[ -x /venv/main/bin/python ]]; then
  PY=/venv/main/bin/python
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  echo 'No usable Python environment found for simnet-transcriber.' >&2
  exit 30
fi

cd "$ROOT"
exec "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8000
