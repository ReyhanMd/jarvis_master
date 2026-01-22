#!/bin/bash
# Fix port 8000 issue

echo "=== Fixing Port 8000 ==="
echo ""

echo "1. Finding processes using port 8000..."
PROCS=$(lsof -ti :8000 2>/dev/null)
if [ -z "$PROCS" ]; then
    echo "   ✅ No processes found on port 8000"
else
    echo "   Found processes: $PROCS"
    echo "   Killing processes..."
    kill -9 $PROCS 2>/dev/null
    sleep 2
    echo "   ✅ Processes killed"
fi

echo ""
echo "2. Verifying port is free..."
if lsof -i :8000 > /dev/null 2>&1; then
    echo "   ⚠️  Port still in use:"
    lsof -i :8000
    echo "   Trying force kill..."
    pkill -9 -f "uvicorn" 2>/dev/null
    pkill -9 -f "python.*8000" 2>/dev/null
    sleep 2
else
    echo "   ✅ Port 8000 is now free"
fi

echo ""
echo "3. Final check..."
if lsof -i :8000 > /dev/null 2>&1; then
    echo "   ⚠️  Port still in use - manual intervention needed"
    echo "   Run: sudo lsof -i :8000"
    echo "   Then: sudo kill -9 <PID>"
else
    echo "   ✅ Port 8000 is free - ready to start backend"
fi

echo ""
echo "=== Ready to Start ==="
echo "Run: ./start_backend_simple.sh"
