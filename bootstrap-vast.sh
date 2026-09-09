#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
ctl() { supervisorctl -c "$ROOT/simnet-supervisord.conf" "$@"; }

say '=== SIMNET TRANSCRIBER BOOTSTRAP ==='

missing=()
for cmd in git curl jq ffmpeg supervisorctl supervisord; do
  have "$cmd" || missing+=("$cmd")
done

if ((${#missing[@]})); then
  if ! have apt-get; then
    say "Missing commands: ${missing[*]}"
    say 'apt-get is unavailable; install dependencies manually.' >&2
    exit 20
  fi
  say "Installing system packages for: ${missing[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y git curl jq ffmpeg supervisor
fi

PY=""
if [[ -x /venv/main/bin/python ]]; then
  PY=/venv/main/bin/python
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  if ! python3 -m venv "$ROOT/.venv" 2>/dev/null; then
    if have apt-get; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y python3-venv
      python3 -m venv "$ROOT/.venv"
    else
      say 'Unable to create Python virtual environment.' >&2
      exit 21
    fi
  fi
  PY="$ROOT/.venv/bin/python"
fi

say "Python: $($PY --version 2>&1)"
PIP_ROOT_USER_ACTION=ignore "$PY" -m pip install --disable-pip-version-check -r requirements.txt

chmod +x "$ROOT/simnet-transcriber-supervisor.sh" "$ROOT/start.sh" "$ROOT/status.sh" "$ROOT/restart.sh" 2>/dev/null || true

# Use a private Supervisor daemon/socket for this project. Vast images may already
# run their own Supervisor instance; sharing its HTTP/socket configuration causes
# port conflicts and makes bootstrap image-dependent.
if ! ctl pid >/dev/null 2>&1; then
  pidfile=/tmp/simnet-transcriber-supervisord.pid
  sock=/tmp/simnet-transcriber-supervisor.sock
  if [[ -f "$pidfile" ]]; then
    oldpid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ ! "$oldpid" =~ ^[0-9]+$ ]] || ! kill -0 "$oldpid" 2>/dev/null; then
      rm -f "$pidfile" "$sock"
    fi
  else
    rm -f "$sock"
  fi
  supervisord -c "$ROOT/simnet-supervisord.conf"
  sleep 1
fi

if ! ctl pid >/dev/null 2>&1; then
  say 'Dedicated SIMNET Supervisor daemon is unavailable.' >&2
  cat /tmp/simnet-transcriber-supervisord.log 2>/dev/null || true
  exit 23
fi

ctl reread >/dev/null
ctl update >/dev/null || true

program_status="$(ctl status simnet-transcriber 2>&1 || true)"
if [[ -z "$program_status" || "$program_status" == *'no such process'* || "$program_status" == *'ERROR'* ]]; then
  say 'Supervisor did not register simnet-transcriber.' >&2
  printf '%s\n' "$program_status" >&2
  exit 24
fi

if [[ "${1:-}" == '--no-start' ]]; then
  say 'Bootstrap complete; service left stopped.'
  exit 0
fi

"$ROOT/start.sh"
say '=== TRANSCRIBER_READY ==='
