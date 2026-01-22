#!/bin/bash
# Script to kill old backend processes and restart cleanly

echo "=== Stopping old backend processes ==="
pkill -f "uvicorn.*main:app" || true
sleep 2

echo "=== Checking for remaining processes ==="
REMAINING=$(ps aux | grep -E "uvicorn.*main:app" | grep -v grep | wc -l | tr -d ' ')
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  Warning: $REMAINING backend processes still running"
    ps aux | grep -E "uvicorn.*main:app" | grep -v grep
    echo "Killing forcefully..."
    pkill -9 -f "uvicorn.*main:app" || true
    sleep 1
fi

echo "=== Verifying port 8000 is free ==="
if lsof -i :8000 > /dev/null 2>&1; then
    echo "⚠️  Port 8000 still in use. Processes:"
    lsof -i :8000
else
    echo "✅ Port 8000 is free"
fi

echo ""
echo "=== Ready to start backend ==="
echo "Run this in Terminal 1:"
echo "  cd /Users/reyhan/shail_master"
echo "  source services_env/bin/activate"
echo "  cd apps/shail"
echo "  uvicorn main:app --reload --host 0.0.0.0 --port 8000"
