#!/bin/bash
#
# Unified one-click startup for SHAIL
#
# Features:
# - Loads .env (GEMINI_API_KEY, etc.)
# - Ensures Python venv and dependencies
# - Starts native services (if on macOS)
# - Starts Redis, Python services, API, worker
# - Health checks with retries
# - PID tracking for stop_shail.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
PID_DIR="$ROOT/run"
VENV="$ROOT/services_env"
ENV_FILE="$ROOT/.env"

mkdir -p "$LOG_DIR" "$PID_DIR"

check_port() {
  local port=$1
  lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1
}

wait_for_port() {
  local name=$1
  local port=$2
  local max_wait=30
  local waited=0
  echo -n "⏳ Waiting for $name on port $port"
  until check_port "$port" || [ $waited -ge $max_wait ]; do
    sleep 1
    waited=$((waited + 1))
    echo -n "."
  done
  if check_port "$port"; then
    echo " ✓"
  else
    echo " ✗ (timeout)"
  fi
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Load .env if present
if [ -f "$ENV_FILE" ]; then
  log "Loading environment from .env"
  set -a
  source "$ENV_FILE"
  set +a
else
  log "No .env found. Proceeding with current environment."
fi

# Ensure venv
if [ ! -d "$VENV" ]; then
  log "Creating Python venv at $VENV"
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

# Install dependencies if needed
install_service() {
  local svc=$1
  if [ ! -f "$ROOT/services/$svc/.installed" ]; then
    log "Installing dependencies for $svc"
    pushd "$ROOT/services/$svc" >/dev/null
    pip install -q -r requirements.txt
    touch .installed
    popd >/dev/null
  fi
}

for svc in ui_twin action_executor vision rag_retriever planner; do
  install_service "$svc"
done
log "Dependencies ready"

# Start Redis if not running
if check_port 6379; then
  log "Redis already running on 6379"
else
  if command -v redis-server >/dev/null 2>&1; then
    log "Starting Redis"
    redis-server >"$LOG_DIR/redis.log" 2>&1 &
    echo $! >"$PID_DIR/redis.pid"
    wait_for_port "Redis" 6379
  else
    log "Redis not installed. Please install (brew install redis)."
  fi
fi

# Start native services (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
  log "Starting native services"
  if [ -f "$ROOT/run_native_services.sh" ]; then
    "$ROOT/run_native_services.sh" >"$LOG_DIR/native.log" 2>&1 &
    echo $! >"$PID_DIR/native.pid"
  else
    log "run_native_services.sh not found. Open Xcode projects manually if needed."
  fi
fi

# Start Python services
start_service() {
  local name=$1
  local dir=$2
  local cmd=$3
  local port=$4
  log "Starting $name"
  pushd "$dir" >/dev/null
  eval "$cmd" >"$LOG_DIR/${name}.log" 2>&1 &
  local pid=$!
  popd >/dev/null
  echo $pid >"$PID_DIR/${name}.pid"
  wait_for_port "$name" "$port"
}

# Start ui_twin as background process (no HTTP server, just WebSocket consumer)
log "Starting ui_twin (background service)"
pushd "$ROOT/services/ui_twin" >/dev/null
python service.py >"$LOG_DIR/ui_twin.log" 2>&1 &
UI_TWIN_PID=$!
popd >/dev/null
echo $UI_TWIN_PID >"$PID_DIR/ui_twin.pid"
log "ui_twin started (PID: $UI_TWIN_PID) - runs in background, no HTTP port"

# Start action_executor on port 8080
start_service "action_executor" "$ROOT/services/action_executor" "python service.py" 8080
start_service "vision" "$ROOT/services/vision" "python service.py" 8081
start_service "rag_retriever" "$ROOT/services/rag_retriever" "python service.py" 8082
start_service "planner" "$ROOT/services/planner" "python service.py" 8083

# Start Shail API
log "Starting Shail API"
pushd "$ROOT/apps/shail" >/dev/null
uvicorn main:app --host 0.0.0.0 --port 8000 >"$LOG_DIR/shail_api.log" 2>&1 &
API_PID=$!
popd >/dev/null
echo $API_PID >"$PID_DIR/shail_api.pid"
wait_for_port "Shail API" 8000

# Start task worker
log "Starting task worker"
pushd "$ROOT" >/dev/null
python -m shail.workers.task_worker >"$LOG_DIR/task_worker.log" 2>&1 &
WORKER_PID=$!
popd >/dev/null
echo $WORKER_PID >"$PID_DIR/task_worker.pid"

log "All services started. Logs in $LOG_DIR; PIDs in $PID_DIR."
