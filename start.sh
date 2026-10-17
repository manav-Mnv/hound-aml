#!/bin/sh
# Start FalkorDB, generate the synthetic banks, then serve the API + UI.
set -e
DATA_DIR="${FALKORDB_DATA:-/tmp/falkordb}"
mkdir -p "$DATA_DIR"

redis-server --port 6379 --bind 127.0.0.1 --dir "$DATA_DIR" --save "" --appendonly no \
  --loadmodule /opt/falkordb/falkordb.so --daemonize yes --logfile "$DATA_DIR/falkordb.log" \
  --pidfile "$DATA_DIR/redis.pid"

i=0
until redis-cli -p 6379 ping >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 100 ]; then cat "$DATA_DIR/falkordb.log"; exit 1; fi
  sleep 0.2
done
echo "FalkorDB is up"

cd /app/backend
python -m hound.cli seed
exec python -m uvicorn hound.api:app --host 0.0.0.0 --port "${PORT:-7860}"
