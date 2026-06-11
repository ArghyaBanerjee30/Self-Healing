#!/bin/bash
# Self-Healing Demo
#
# Starts:
#   1. The demo commerce API  (uvicorn on :8000)
#   2. The self-healing pipeline  (LogWatcher → Categoriser → Supervisor)
#
# Then YOU hit endpoints manually in another terminal.
# Clean endpoints → pipeline waits silently.
# Buggy endpoints → error logged → pipeline fires automatically.
#
# Usage:
#   ./run_demo.sh                    # start server + pipeline
#   ./run_demo.sh --skip-transient   # skip the transient gate (faster for demos)
#   ./run_demo.sh --traffic          # also start the auto traffic simulator
#
# Ctrl+C stops everything.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT/repo_data/demo-commerce-api"
LOG_FILE="$APP_DIR/logs/production.log"
VENV="$ROOT/.venv/bin/activate"
EXTRA_FLAGS=""
WITH_TRAFFIC=false

for arg in "$@"; do
  case $arg in
    --skip-transient) EXTRA_FLAGS="$EXTRA_FLAGS --skip-transient" ;;
    --traffic)        WITH_TRAFFIC=true ;;
  esac
done

cleanup() {
  echo ""
  echo "Stopping..."
  kill "$APP_PID" "$PIPELINE_PID" "${TRAFFIC_PID:-}" 2>/dev/null
  wait "$APP_PID" "$PIPELINE_PID" "${TRAFFIC_PID:-}" 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

source "$VENV"

mkdir -p "$(dirname "$LOG_FILE")"
# Clear stale log so old errors don't replay on startup
> "$LOG_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Self-Healing Demo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Start the API server
echo ""
echo "[1/2] Starting demo-commerce-api on http://localhost:8000 ..."
cd "$APP_DIR"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level error 2>/dev/null &
APP_PID=$!
cd "$ROOT"

echo "      Waiting for server..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "      Server is up."
    break
  fi
  sleep 1
done

# 2. Start the self-healing pipeline
echo ""
echo "[2/2] Starting self-healing pipeline (watching logs/production.log) ..."
python "$ROOT/main.py" \
  --log "$LOG_FILE" \
  --config "$APP_DIR/self-healing.yaml" \
  $EXTRA_FLAGS &
PIPELINE_PID=$!

sleep 1

# 3. Optional traffic simulator
if [ "$WITH_TRAFFIC" = true ]; then
  echo ""
  echo "[+] Auto traffic simulator running (--traffic flag set)"
  python "$APP_DIR/scripts/simulate_traffic.py" --rate 0.5 &
  TRAFFIC_PID=$!
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Ready. Open a new terminal and hit endpoints:"
echo ""
echo "  ✅  No error (pipeline stays silent):"
echo "      curl http://localhost:8000/health"
echo "      curl http://localhost:8000/orders"
echo "      curl -X POST http://localhost:8000/payments/order-001"
echo "      curl http://localhost:8000/inventory/prod-apple/unit-price"
echo ""
echo "  💥  Triggers self-healing:"
echo "      curl -X POST http://localhost:8000/payments/order-ghost"
echo "      curl http://localhost:8000/inventory/prod-banana/unit-price"
echo "      curl -X POST http://localhost:8000/checkout/preview \\"
echo "           -H 'Content-Type: application/json' \\"
echo "           -d '{\"cart\":[]}'"
echo ""
echo "  Press Ctrl+C to stop everything."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

wait "$APP_PID" "$PIPELINE_PID"
