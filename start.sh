#!/bin/sh
# Startup script — starts bgutil PO token server then FastAPI

# Start bgutil on port 4416 (must be explicit — Render sets PORT=8000)
PORT=4416 node /bgutil/server/build/main.js &
BGUTIL_PID=$!

# Wait up to 10 seconds for bgutil to accept connections
echo "Waiting for bgutil server to start on port 4416..."
i=0
while [ $i -lt 10 ]; do
  if wget -q --spider http://127.0.0.1:4416/ping 2>/dev/null; then
    echo "bgutil server is ready"
    break
  fi
  sleep 1
  i=$((i+1))
done

if [ $i -eq 10 ]; then
  echo "WARNING: bgutil server did not respond in time, continuing anyway"
fi

# Start FastAPI (exec replaces this shell so Render tracks uvicorn's PID)
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --timeout-keep-alive 75
