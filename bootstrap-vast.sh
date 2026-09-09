#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

say '=== SIMNET TRANSCRIBER BOOTSTRAP ==='

missing=()
for cmd in git curl jq ffmpeg supervisorctl; do
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
"$PY" -m pip install --disable-pip-version-check -r requirements.txt

install -d /opt/supervisor-scripts
install -m 0755 "$ROOT/simnet-transcriber-supervisor.sh" /opt/supervisor-scripts/simnet-transcriber.sh

CONF_DIR=''
for candidate in /etc/supervisor/conf.d /etc/supervisord.d; do
  if [[ -d "$candidate" ]]; then CONF_DIR="$candidate"; break; fi
done
if [[ -z "$CONF_DIR" ]]; then
  say 'Supervisor config directory not found.' >&2
  exit 22
fi
install -m 0644 "$ROOT/simnet-transcriber.conf" "$CONF_DIR/simnet-transcriber.conf"

supervisorctl reread >/dev/null
supervisorctl update >/dev/null || true

if ! supervisorctl status simnet-transcriber >/dev/null 2>&1; then
  say 'Supervisor did not register simnet-transcriber.' >&2
  exit 23
fi

if [[ "${1:-}" == '--no-start' ]]; then
  say 'Bootstrap complete; service left stopped.'
  exit 0
fi

"$ROOT/start.sh"
say '=== TRANSCRIBER_READY ==='
