#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

exec uvicorn backend.config.asgi:application \
  --host "${BACKEND_HOST:-127.0.0.1}" \
  --port "${BACKEND_PORT:-8000}" \
  --workers "${BACKEND_WORKERS:-2}" \
  --timeout-keep-alive "${BACKEND_TIMEOUT_KEEP_ALIVE:-120}"
