#!/bin/bash
set -euo pipefail
if supervisorctl status simnet-transcriber 2>/dev/null | grep -q RUNNING; then
    echo "simnet-transcriber is already running"
else
    supervisorctl start simnet-transcriber >/dev/null
fi
for attempt in {1..60}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/health | jq -e '.ok == true' >/dev/null 2>&1; then
        supervisorctl status simnet-transcriber
        curl -fsS http://127.0.0.1:8000/health | jq .
        exit 0
    fi
    sleep 1
done
echo "Backend did not become healthy within 60 seconds" >&2
exit 1
