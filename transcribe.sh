#!/bin/bash
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then echo "Usage: $0 FILE [PROFILE]" >&2; exit 2; fi
file="$1"; profile="${2:-}"
if [[ ! -f "$file" ]]; then echo "File not found: $file" >&2; exit 2; fi
args=(-fsS --max-time 3600 -X POST -F "file=@$file" -F "language=auto")
[[ -z "$profile" ]] || args+=(-F "profile=$profile")
response_file="$(mktemp /tmp/simnet-transcribe.XXXXXX)"
trap 'rm -f "$response_file"' EXIT
http_code="$(curl "${args[@]}" -o "$response_file" -w '%{http_code}' http://127.0.0.1:8000/transcribe || true)"
if [[ "$http_code" != "200" ]]; then
    echo "Transcription failed (HTTP ${http_code:-connection error}):" >&2
    jq -r '.detail // .' "$response_file" 2>/dev/null >&2 || sed -n '1,20p' "$response_file" >&2
    exit 1
fi
jq -r '"Profile: \(.profile)\nLanguage: \(.language)\nDuration: \(.duration_seconds) s\nProcessing: \(.processing_seconds) s\nRealtime factor: \(.realtime_factor // "n/a")\n\nTranscript:\n\(.text)"' "$response_file"
