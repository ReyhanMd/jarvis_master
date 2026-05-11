#!/bin/bash
#
# Unified one-click startup for SHAIL
#
# Features:
# - Loads .env
# - Starts Ollama + pulls required models
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
PYTHON_BIN="$VENV/bin/python3"

mkdir -p "$LOG_DIR" "$PID_DIR"

check_port() {
  local port=$1
  lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1
}

wait_for_port() {
  local name=$1
  local port=$2
  local max_wait="${3:-30}"
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
if [ ! -x "$PYTHON_BIN" ]; then
  log "Python venv is missing its interpreter at $PYTHON_BIN"
  exit 1
fi

# Install dependencies if needed
install_service() {
  local svc=$1
  if [ ! -f "$ROOT/services/$svc/.installed" ]; then
    log "Installing dependencies for $svc"
    pushd "$ROOT/services/$svc" >/dev/null
    "$PYTHON_BIN" -m pip install -q -r requirements.txt
    touch .installed
    popd >/dev/null
  fi
}

for svc in ui_twin action_executor vision rag_retriever planner; do
  install_service "$svc"
done
log "Dependencies ready"

# Start Ollama if not running
if check_port 11434; then
  log "Ollama already running on 11434"
else
  if command -v ollama >/dev/null 2>&1; then
    log "Starting Ollama"
    # Heat / RAM caps: never keep both chat + vision resident, single
    # concurrent infer. Reduces fan ramp on M-series.
    export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
    export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
    export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"
    ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
    echo $! >"$PID_DIR/ollama.pid"
    wait_for_port "Ollama" 11434
    log "Pulling required models (this may take a while on first run)"
    # Sprint 6: switched chat default to quantized Gemma 3 4B (Q4_K_M).
    # Saves ~7 GB resident vs. gemma4:e4b. Vision deferred — Ghost Cursor
    # pulls llava:7b on first use only.
    ollama pull gemma3:4b-it-q4_K_M || true
    ollama pull nomic-embed-text || true
  else
    log "WARNING: ollama not found. Install from https://ollama.com"
  fi
fi

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

  # Build + install + start MemoryWatchdog (Swift CLI, menu bar app)
  # NOTE: launches from ~/Applications/SHAIL/MemoryWatchdog (stable path) so
  # macOS Accessibility / Screen Recording grants survive rebuilds. See
  # scripts/install_watchdog.sh for why.
  WATCHDOG_DIR="$ROOT/native/mac/MemoryWatchdog"
  WATCHDOG_INSTALLED="$HOME/Applications/SHAIL/MemoryWatchdog"
  WATCHDOG_MODULE_CACHE="$WATCHDOG_DIR/.module-cache"
  if [ -d "$WATCHDOG_DIR" ] && command -v swift >/dev/null 2>&1; then
    log "Building MemoryWatchdog…"
    rm -rf "$WATCHDOG_DIR/.build"
    mkdir -p "$WATCHDOG_MODULE_CACHE"
    if (
      cd "$WATCHDOG_DIR" && \
      CLANG_MODULE_CACHE_PATH="$WATCHDOG_MODULE_CACHE" \
      SWIFT_DRIVER_CLANG_MODULE_CACHE_PATH="$WATCHDOG_MODULE_CACHE" \
      swift build -c release --quiet
    ); then
      bash "$ROOT/scripts/install_watchdog.sh" >>"$LOG_DIR/memory_watchdog.log" 2>&1 || true
      if [ -f "$WATCHDOG_INSTALLED" ]; then
        log "Starting MemoryWatchdog (installed path)"
        "$WATCHDOG_INSTALLED" >>"$LOG_DIR/memory_watchdog.log" 2>&1 &
        echo $! >"$PID_DIR/memory_watchdog.pid"
      else
        log "MemoryWatchdog install failed — check $LOG_DIR/memory_watchdog.log"
      fi
    else
      log "MemoryWatchdog build failed — check $LOG_DIR/memory_watchdog.log"
    fi
  fi
fi

# Start Python services
start_service() {
  local name=$1
  local dir=$2
  local cmd=$3
  local port=$4
  local max_wait="${5:-30}"
  log "Starting $name"
  pushd "$dir" >/dev/null
  "$PYTHON_BIN" $cmd >"$LOG_DIR/${name}.log" 2>&1 &
  local pid=$!
  popd >/dev/null
  echo $pid >"$PID_DIR/${name}.pid"
  wait_for_port "$name" "$port" "$max_wait"
}

# Start ui_twin as background process (no HTTP server, just WebSocket consumer)
log "Starting ui_twin (background service)"
pushd "$ROOT/services/ui_twin" >/dev/null
"$PYTHON_BIN" service.py >"$LOG_DIR/ui_twin.log" 2>&1 &
UI_TWIN_PID=$!
popd >/dev/null
echo $UI_TWIN_PID >"$PID_DIR/ui_twin.pid"
log "ui_twin started (PID: $UI_TWIN_PID) - runs in background, no HTTP port"

# Start action_executor on port 8080
start_service "action_executor" "$ROOT/services/action_executor" "service.py" 8080
start_service "vision" "$ROOT/services/vision" "service.py" 8081
start_service "rag_retriever" "$ROOT/services/rag_retriever" "service.py" 8082 60
start_service "planner" "$ROOT/services/planner" "service.py" 8083

# Start Shail API
log "Starting Shail API"
if check_port 8000; then
  log "Port 8000 already in use — assuming Shail API already running"
else
  pushd "$ROOT/apps/shail" >/dev/null
  "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port 8000 >"$LOG_DIR/shail_api.log" 2>&1 &
  API_PID=$!
  popd >/dev/null
  echo $API_PID >"$PID_DIR/shail_api.pid"
  wait_for_port "Shail API" 8000
  if ! check_port 8000; then
    log "✗ Shail API failed to bind — see $LOG_DIR/shail_api.log"
    log "Last 20 lines:"
    tail -n 20 "$LOG_DIR/shail_api.log" || true
    exit 1
  fi
  log "Shail API health: $(curl -s http://127.0.0.1:8000/health || echo unreachable)"
fi

# Start task worker
log "Starting task worker"
pushd "$ROOT" >/dev/null
"$PYTHON_BIN" -m shail.workers.task_worker >"$LOG_DIR/task_worker.log" 2>&1 &
WORKER_PID=$!
popd >/dev/null
echo $WORKER_PID >"$PID_DIR/task_worker.pid"

log "All services started. Logs in $LOG_DIR; PIDs in $PID_DIR."
