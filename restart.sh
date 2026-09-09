#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ctl() { supervisorctl -c "$ROOT/simnet-supervisord.conf" "$@"; }
ctl restart simnet-transcriber >/dev/null
for attempt in {1..60}; do
    if health="$(curl -fsS --max-time 3 http://127.0.0.1:8000/health 2>/dev/null)" && jq -e '.ok == true' >/dev/null <<<"$health"; then
        ctl status simnet-transcriber || true
        jq . <<<"$health"
        exit 0
    fi
    sleep 1
done
echo "Backend did not become healthy within 60 seconds" >&2
ctl status simnet-transcriber >&2 || true
exit 1
