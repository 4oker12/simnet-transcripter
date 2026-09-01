#!/bin/bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Supervisor: $(supervisorctl status simnet-transcriber 2>&1)"
pid="$(supervisorctl pid simnet-transcriber 2>/dev/null || true)"
[[ "$pid" =~ ^[0-9]+$ ]] || pid="-"
echo "Backend PID: $pid"
if health="$(curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null)"; then
    echo "Health: $(jq -c . <<<"$health")"
    echo "Profile/model: $(jq -r '"default=" + .default_profile + " model=" + .model + " device=" + .device + " compute=" + .compute_type' <<<"$health")"
else
    echo "Health: UNREACHABLE"
    echo "Configured default: $(jq -r '.default' "$ROOT/config/asr_profiles.json" 2>/dev/null || echo unknown)"
fi
gpu="$(nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || true)"
echo "GPU: ${gpu:-unavailable}"
echo "Disk: $(df -h /workspace | awk 'NR==2 {print $4 " free (" $5 " used)"}')"
