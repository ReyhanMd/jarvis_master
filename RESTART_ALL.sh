#!/bin/bash

# Master restart script for all Shail services
# This script will start Redis, Worker, API, and UI in the correct order

set -e  # Exit on error

PROJECT_ROOT="/Users/reyhan/shail_master"
cd "$PROJECT_ROOT"

echo "======================================"
echo "🚀 SHAIL MASTER RESTART SCRIPT"
echo "======================================"
echo ""

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if a port is in use
port_in_use() {
    lsof -i :"$1" >/dev/null 2>&1
}

# 1. Check prerequisites
echo "📋 Checking prerequisites..."

if ! command_exists redis-server; then
    echo "❌ ERROR: redis-server not found"
    echo "   Install with: brew install redis"
    exit 1
fi

if ! command_exists node; then
    echo "❌ ERROR: node not found"
    echo "   Install with: brew install node"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  WARNING: .env file not found"
    echo "   Copy .env.example to .env and add your GEMINI_API_KEY"
    echo ""
fi

echo "✓ Prerequisites check passed"
echo ""

# 2. Clear old failed tasks (inline)
echo "🧹 Cleaning old failed tasks from database..."
if [ -f "shail_memory.sqlite3" ]; then
    sqlite3 shail_memory.sqlite3 "DELETE FROM tasks WHERE status = 'failed';" 2>/dev/null || true
    echo "✓ Old failed tasks cleared"
else
    echo "✓ Database doesn't exist yet, will be created automatically"
fi
echo ""

# 3. Check and start Redis
echo "📊 Starting Redis..."
if port_in_use 6379; then
    echo "✓ Redis already running on port 6379"
else
    redis-server --daemonize yes --port 6379
    sleep 2
    if port_in_use 6379; then
        echo "✓ Redis started on port 6379"
    else
        echo "❌ Failed to start Redis"
        exit 1
    fi
fi
echo ""

# 4. Start Worker in background
echo "🧠 Starting Shail Worker..."
if pgrep -f "task_worker" > /dev/null; then
    echo "⚠️  Worker already running, killing it first..."
    pkill -f "task_worker"
    sleep 2
fi

# Start worker in background and save PID
nohup ./start_worker.sh > worker.log 2>&1 &
WORKER_PID=$!
echo "✓ Worker started (PID: $WORKER_PID, logs: worker.log)"
sleep 3
echo ""

# 5. Start API in background
echo "🌐 Starting Shail API..."
if port_in_use 8000; then
    echo "⚠️  API already running on port 8000, killing it first..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Start API in background
cd "$PROJECT_ROOT"

# Use virtual environment's uvicorn if available
if [ -f "jarvis-env/bin/uvicorn" ]; then
    UVICORN_CMD="jarvis-env/bin/uvicorn"
    echo "  Using virtual environment uvicorn"
elif command_exists uvicorn; then
    UVICORN_CMD="uvicorn"
    echo "  Using system uvicorn"
else
    echo "❌ ERROR: uvicorn not found"
    echo "   Install with: pip install uvicorn"
    echo "   Or activate virtual environment: source jarvis-env/bin/activate && pip install uvicorn"
    exit 1
fi

nohup $UVICORN_CMD apps.shail.main:app --reload --host 0.0.0.0 --port 8000 > api.log 2>&1 &
API_PID=$!
echo "✓ API started (PID: $API_PID, logs: api.log)"
sleep 3
echo ""

# 6. Start UI in background
echo "🎨 Starting Shail UI..."
cd "$PROJECT_ROOT/apps/shail-ui"

if port_in_use 3000; then
    echo "⚠️  UI already running on port 3000, killing it first..."
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "📦 Installing UI dependencies..."
    npm install
fi

# Start UI in background
nohup npm run dev > "$PROJECT_ROOT/ui.log" 2>&1 &
UI_PID=$!
echo "✓ UI started (PID: $UI_PID, logs: ui.log)"
sleep 3
echo ""

# 7. Summary
echo "======================================"
echo "✅ ALL SERVICES STARTED SUCCESSFULLY"
echo "======================================"
echo ""
echo "📊 Redis:       Running on port 6379"
echo "🧠 Worker:      Running (PID: $WORKER_PID)"
echo "🌐 API:         Running on http://localhost:8000"
echo "🎨 UI:          Running on http://localhost:3000"
echo ""
echo "📝 Logs:"
echo "   Worker: tail -f worker.log"
echo "   API:    tail -f api.log"
echo "   UI:     tail -f ui.log"
echo ""
echo "🔥 To stop all services:"
echo "   kill $WORKER_PID $API_PID $UI_PID"
echo "   redis-cli shutdown"
echo ""
echo "🚀 Open your browser to: http://localhost:3000"
echo ""

