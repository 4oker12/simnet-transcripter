#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ctl() { supervisorctl -c "$ROOT/simnet-supervisord.conf" "$@"; }

if ! ctl pid >/dev/null 2>&1; then
    echo 'simnet-transcriber supervisor is already stopped'
    exit 0
fi

ctl stop simnet-transcriber >/dev/null 2>&1 || true
for _ in {1..10}; do
    status="$(ctl status simnet-transcriber 2>/dev/null || true)"
    if ! grep -qE 'RUNNING|STARTING|STOPPING' <<<"$status"; then
        break
    fi
    sleep 1
done
ctl shutdown >/dev/null 2>&1 || true
sleep 1
rm -f /tmp/simnet-transcriber-supervisor.sock /tmp/simnet-transcriber-supervisord.pid 2>/dev/null || true
echo 'simnet-transcriber: STOPPED'
