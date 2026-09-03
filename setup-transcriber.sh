#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPERVISOR_PROGRAM="simnet-transcriber"
SUPERVISOR_WRAPPER="/opt/supervisor-scripts/simnet-transcriber.sh"
SUPERVISOR_CONF="/etc/supervisor/conf.d/simnet-transcriber.conf"

log() { printf '[setup] %s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1; }

log "workspace: $ROOT"
df -h "$ROOT" | sed -n '1,2p'

missing_packages=()
need_cmd ffmpeg || missing_packages+=(ffmpeg)
need_cmd ffprobe || missing_packages+=(ffmpeg)
need_cmd jq || missing_packages+=(jq)
need_cmd supervisorctl || missing_packages+=(supervisor)

if ((${#missing_packages[@]})); then
  if ! need_cmd apt-get; then
    printf 'Missing required commands and apt-get is unavailable: %s\n' "${missing_packages[*]}" >&2
    exit 1
  fi
  log "installing OS packages: ${missing_packages[*]}"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_packages[@]}"
fi

if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON_BIN="$VIRTUAL_ENV/bin/python"
elif [[ -x /venv/main/bin/python ]]; then
  PYTHON_BIN="/venv/main/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  need_cmd python3 || { echo 'python3 not found' >&2; exit 1; }
  log "creating local virtual environment"
  python3 -m venv "$ROOT/.venv"
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

log "python: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/logs" "$ROOT/tmp" "$ROOT/models" /opt/supervisor-scripts /etc/supervisor/conf.d
install -m 0755 "$ROOT/simnet-transcriber-supervisor.sh" "$SUPERVISOR_WRAPPER"

sed \
  -e "s#SIMNET_TRANSCRIBER_DIR=\"/workspace/simnet-transcripter\"#SIMNET_TRANSCRIBER_DIR=\"$ROOT\"#" \
  -e "s#SIMNET_PYTHON=\"/venv/main/bin/python\"#SIMNET_PYTHON=\"$PYTHON_BIN\"#" \
  -e "s#directory=/workspace/simnet-transcripter#directory=$ROOT#" \
  "$ROOT/simnet-transcriber.conf" > "$SUPERVISOR_CONF"

supervisorctl reread
supervisorctl update

log "syntax check"
"$PYTHON_BIN" -m py_compile "$ROOT/app.py"

log "starting service"
"$ROOT/start.sh"

log "capabilities"
curl -fsS http://127.0.0.1:8000/capabilities | jq .

log "ready"
