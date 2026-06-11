#!/bin/bash
# Full self-healing demo — one script to run everything.
#
# Starts:
#   1. The demo commerce API (uvicorn on :8000)
#   2. The self-healing pipeline (LogWatcher → Categoriser → Supervisor)
#   3. The traffic simulator (realistic mixed HTTP requests)
#
# Usage:
#   ./run_demo.sh
#   ./run_demo.sh --rate 2      # 2 requests/sec traffic
#   ./run_demo.sh --skip-transient   # route every signal straight to Supervisor
#
# Ctrl+C stops everything.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT/repo_data/demo-commerce-api"
LOG_FILE="$APP_DIR/logs/production.log"
VENV="$ROOT/.venv/bin/activate"
RATE="${RATE:-0.5}"
EXTRA_FLAGS=""

for arg in "$@"; do
  case $arg in
    --rate=*) RATE="${arg#*=}" ;;
    --rate)   shift; RATE="$1" ;;
    --skip-transient) EXTRA_FLAGS="$EXTRA_FLAGS --skip-transient" ;;
  esac
done

cleanup() {
  echo ""
  echo "Stopping all processes..."
  kill "$APP_PID" "$PIPELINE_PID" "$TRAFFIC_PID" 2>/dev/null
  wait "$APP_PID" "$PIPELINE_PID" "$TRAFFIC_PID" 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

source "$VENV"

# Ensure log file exists
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Self-Healing Demo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Start the API server
echo "[1/3] Starting demo-commerce-api on http://localhost:8000 ..."
cd "$APP_DIR"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level error 2>/dev/null &
APP_PID=$!
cd "$ROOT"

# Wait for the server to be ready
echo "      Waiting for server..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "      Server ready."
    break
  fi
  sleep 1
done

# 2. Start the self-healing pipeline
echo "[2/3] Starting self-healing pipeline (watching $LOG_FILE) ..."
python "$ROOT/main.py" \
  --log "$LOG_FILE" \
  --config "$APP_DIR/self-healing.yaml" \
  $EXTRA_FLAGS 2>&1 &
PIPELINE_PID=$!

sleep 2

# 3. Start the traffic simulator
echo "[3/3] Starting traffic simulator at ${RATE} req/s ..."
echo "      Mix: ~80% valid requests, ~20% edge cases that trigger bugs"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  All systems running. Press Ctrl+C to stop."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python "$APP_DIR/scripts/simulate_traffic.py" --rate "$RATE" &
TRAFFIC_PID=$!

# Wait for any process to exit (or Ctrl+C)
wait "$APP_PID" "$PIPELINE_PID" "$TRAFFIC_PID"
