#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$ROOT/config/asr_profiles.json"
command="${1:-}"
case "$command" in
    list) jq -r '.profiles | keys[]' "$CONFIG" ;;
    show) jq -r '.default' "$CONFIG" ;;
    baseline|simnet)
        current="$(jq -r '.default' "$CONFIG")"
        if [[ "$current" == "$command" ]]; then
            echo "Default profile is already $command"
        else
            temporary="$(mktemp "$ROOT/config/.asr_profiles.XXXXXX")"
            trap 'rm -f "$temporary"' EXIT
            jq --arg name "$command" '.default = $name' "$CONFIG" >"$temporary"
            chmod --reference="$CONFIG" "$temporary"
            mv "$temporary" "$CONFIG"
            trap - EXIT
            echo "Default profile changed: $current -> $command (restart not required)"
        fi
        if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
            curl -fsS http://127.0.0.1:8000/health | jq '{ok, default_profile, model, device}'
        else
            echo "Backend is not reachable; config applies on next start" >&2
        fi ;;
    *) echo "Usage: $0 {list|show|baseline|simnet}" >&2; exit 2 ;;
esac
