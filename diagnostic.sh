#!/bin/bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${SIMNET_TRANSCRIBER_URL:-http://127.0.0.1:8000}"

section() { printf '\n=== %s ===\n' "$1"; }

section "SERVICE"
supervisorctl status simnet-transcriber 2>&1 || true

section "HEALTH"
curl -fsS --max-time 5 "$BASE_URL/health" 2>/dev/null | jq . || echo "UNREACHABLE: $BASE_URL/health"

section "CAPABILITIES"
curl -fsS --max-time 5 "$BASE_URL/capabilities" 2>/dev/null | jq . || echo "UNREACHABLE: $BASE_URL/capabilities"

section "GPU"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>&1 || true

section "CUDA / CTranslate2"
python_bin="${SIMNET_PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    python_bin="$VIRTUAL_ENV/bin/python"
  elif [[ -x /venv/main/bin/python ]]; then
    python_bin=/venv/main/bin/python
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    python_bin="$ROOT/.venv/bin/python"
  else
    python_bin=python3
  fi
fi
"$python_bin" - <<'PY' 2>&1 || true
try:
    import ctranslate2
    print("CUDA devices:", ctranslate2.get_cuda_device_count())
    if ctranslate2.get_cuda_device_count():
        print("CUDA compute types:", ctranslate2.get_supported_compute_types("cuda"))
except Exception as exc:
    print("CTranslate2 check failed:", exc)
PY

section "DISK"
df -h "$ROOT" 2>&1 | sed -n '1,2p'

section "RUNTIME DIRS"
for path in logs tmp models; do
  if [[ -e "$ROOT/$path" ]]; then
    du -sh "$ROOT/$path" 2>/dev/null || true
  else
    echo "$path: missing"
  fi
done

section "RECENT LOG"
tail -n 40 "$ROOT/logs/server.log" 2>/dev/null || echo "server.log unavailable"
