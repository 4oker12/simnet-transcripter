#!/bin/bash
set -euo pipefail
supervisorctl stop simnet-transcriber
supervisorctl status simnet-transcriber || true
