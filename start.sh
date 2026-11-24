#!/bin/sh
# Starts the FastAPI backend on 8000, then the Vite dev server on $PORT.
set -e
cd "$(dirname "$0")"
cd backend
uv sync > /dev/null 2>&1 || true
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning > /tmp/backend.log 2>&1 &
cd ..
exec vp dev --port "${PORT:-3000}" --host 0.0.0.0
