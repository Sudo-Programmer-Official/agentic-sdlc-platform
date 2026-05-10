#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
WEB_DIR="$ROOT_DIR/apps/web"
LOG_DIR="${DEV_STACK_LOG_DIR:-$ROOT_DIR/.dev-stack}"
PID_FILE="$LOG_DIR/dev_stack.pids"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
VITE_API_BASE="${VITE_API_BASE:-http://localhost:${API_PORT}/api/v1}"

mkdir -p "$LOG_DIR"

if [[ ! -x "$API_DIR/.venv/bin/python" ]]; then
  echo "Missing API virtualenv at $API_DIR/.venv/bin/python" >&2
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping dev stack..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
  rm -f "$PID_FILE"
  exit "$exit_code"
}

start_process() {
  local name="$1"
  local workdir="$2"
  shift 2
  local log_file="$LOG_DIR/$name.log"
  (
    cd "$workdir"
    exec "$@"
  ) >"$log_file" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  printf "%-10s pid=%-6s log=%s\n" "$name" "$pid" "$log_file"
}

declare -a PIDS=()
trap cleanup INT TERM EXIT

cleanup_stale_stack() {
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  pkill -f "uvicorn app.main:app --reload --host 0.0.0.0 --port $API_PORT" 2>/dev/null || true
  pkill -f "python -m app.runtime.scheduler_service" 2>/dev/null || true
  pkill -f "python -m app.runtime.worker_service" 2>/dev/null || true
  pkill -f "npm run dev -- --host 0.0.0.0 --port $WEB_PORT" 2>/dev/null || true
}

cleanup_stale_stack

echo "Starting Agentic SDLC local stack"
echo "Logs: $LOG_DIR"
echo

start_process api "$API_DIR" "$API_DIR/.venv/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port "$API_PORT"
start_process scheduler "$API_DIR" "$API_DIR/.venv/bin/python" -m app.runtime.scheduler_service
start_process worker "$API_DIR" "$API_DIR/.venv/bin/python" -m app.runtime.worker_service
start_process web "$WEB_DIR" env VITE_API_BASE="$VITE_API_BASE" npm run dev -- --host 0.0.0.0 --port "$WEB_PORT"

printf "%s\n" "${PIDS[@]}" > "$PID_FILE"

echo
echo "API: http://localhost:$API_PORT"
echo "Web: http://localhost:$WEB_PORT"
echo "Scheduler and Worker logs are in $LOG_DIR/scheduler.log and $LOG_DIR/worker.log"
echo "Press Ctrl+C to stop all processes."

wait
