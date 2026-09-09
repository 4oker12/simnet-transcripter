#!/bin/bash
set -euo pipefail

TIMEOUT="${SIMNET_START_TIMEOUT_SECONDS:-600}"

if supervisorctl status simnet-transcriber 2>/dev/null | grep -q RUNNING; then
    echo "simnet-transcriber is already running"
else
    supervisorctl start simnet-transcriber >/dev/null
fi

for ((attempt=1; attempt<=TIMEOUT; attempt++)); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/health | jq -e '.ok == true' >/dev/null 2>&1; then
        supervisorctl status simnet-transcriber
        curl -fsS http://127.0.0.1:8000/health | jq .
        exit 0
    fi
    sleep 1
done

echo "Backend did not become healthy within ${TIMEOUT} seconds" >&2
supervisorctl status simnet-transcriber 2>/dev/null || true
exit 1
