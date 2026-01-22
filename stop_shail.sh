#!/bin/bash
# Gracefully stop all SHAIL services started by start_shail.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$ROOT/run"

stop_pid() {
  local name=$1
  local file="$PID_DIR/${name}.pid"
  if [ -f "$file" ]; then
    local pid
    pid=$(cat "$file")
    if ps -p "$pid" >/dev/null 2>&1; then
      echo "Stopping $name (pid $pid)"
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$file"
  fi
}

# Stop services in reverse order
stop_pid "task_worker"
stop_pid "shail_api"
stop_pid "planner"
stop_pid "rag_retriever"
stop_pid "vision"
stop_pid "action_executor"
stop_pid "ui_twin"
stop_pid "native"
stop_pid "redis"

echo "All known SHAIL services stopped."
