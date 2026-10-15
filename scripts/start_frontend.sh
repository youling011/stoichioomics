#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/frontend"

if [ ! -f dist/index.html ]; then
  npm run build
fi

exec npm run preview -- \
  --host "${FRONTEND_HOST:-127.0.0.1}" \
  --port "${FRONTEND_PORT:-5173}"
