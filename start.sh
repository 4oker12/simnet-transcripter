#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT="${SIMNET_START_TIMEOUT_SECONDS:-600}"
ctl() { supervisorctl -c "$ROOT/simnet-supervisord.conf" "$@"; }

status="$(ctl status simnet-transcriber 2>/dev/null || true)"
if grep -q 'RUNNING' <<<"$status"; then
    echo "simnet-transcriber is already running"
else
    ctl start simnet-transcriber >/dev/null
fi

for ((attempt=1; attempt<=TIMEOUT; attempt++)); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/health | jq -e '.ok == true' >/dev/null 2>&1; then
        ctl status simnet-transcriber || true
        curl -fsS http://127.0.0.1:8000/health | jq .
        exit 0
    fi
    sleep 1
done

echo "Backend did not become healthy within ${TIMEOUT} seconds" >&2
ctl status simnet-transcriber 2>/dev/null || true
exit 1
