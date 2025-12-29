#!/bin/bash

# start_shail.command
# One-click launcher for SHAIL (Symbiotic OS)

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "🚀 Starting SHAIL (Self-Healing AI Layer)..."

# 1. Kill any existing instances (simple cleanup)
pkill -f "apps/shail/api/server.py"
echo "🧹 Cleaned up old server instances."

# 2. Start the Python Brain Backend
echo "🧠 Waking up the Brain (Master Planner)..."
python3 apps/shail/api/server.py > /tmp/shail_server.log 2>&1 &
SERVER_PID=$!

# 3. Wait for the server to be ready
echo "⏳ Waiting for Brain to come online..."
MAX_RETRIES=30
count=0
while ! curl -s http://localhost:8000/ > /dev/null; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        echo "❌ Error: Brain failed to start. Check /tmp/shail_server.log"
        kill $SERVER_PID
        exit 1
    fi
    echo -n "."
done
echo ""
echo "✅ Brain is online!"

# 4. Launch the Native UI
echo "🎨 Launching SHAIL UI..."
cd apps/mac/ShailUI
swift run ShailUI

# Use this if you compiled a binary instead:
# ./apps/mac/ShailUI/.build/debug/ShailUI

# cleanup on exit
kill $SERVER_PID
