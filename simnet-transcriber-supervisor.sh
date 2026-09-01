#!/bin/bash
set -eo pipefail
utils=/opt/supervisor-scripts/utils
. "${utils}/logging.sh"
. "${utils}/environment.sh"
source /venv/main/bin/activate
cd /workspace/simnet-transcriber
exec /venv/main/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
