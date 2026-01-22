#!/bin/bash
# Comprehensive diagnostic script

echo "=== SHAIL System Diagnostics ==="
echo ""

echo "1. Checking backend processes..."
BACKEND_COUNT=$(ps aux | grep -E "uvicorn.*main:app" | grep -v grep | wc -l | tr -d ' ')
if [ "$BACKEND_COUNT" -eq 0 ]; then
    echo "   ❌ No backend processes running"
elif [ "$BACKEND_COUNT" -eq 1 ]; then
    echo "   ✅ 1 backend process running"
    ps aux | grep -E "uvicorn.*main:app" | grep -v grep
else
    echo "   ⚠️  $BACKEND_COUNT backend processes running (should be 1)"
    ps aux | grep -E "uvicorn.*main:app" | grep -v grep
fi

echo ""
echo "2. Checking port 8000..."
if lsof -i :8000 > /dev/null 2>&1; then
    echo "   ⚠️  Port 8000 is in use:"
    lsof -i :8000 | grep LISTEN
else
    echo "   ✅ Port 8000 is free"
fi

echo ""
echo "3. Testing backend health..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ Backend is responding"
    curl -s http://localhost:8000/health
else
    echo "   ❌ Backend is not responding"
fi

echo ""
echo "4. Checking virtual environment..."
if [ -d "/Users/reyhan/shail_master/services_env" ]; then
    echo "   ✅ services_env exists"
    if [ -f "/Users/reyhan/shail_master/services_env/bin/activate" ]; then
        echo "   ✅ activate script exists"
    else
        echo "   ❌ activate script missing"
    fi
else
    echo "   ❌ services_env directory missing"
fi

echo ""
echo "5. Checking required packages..."
if [ -f "/Users/reyhan/shail_master/services_env/bin/python" ]; then
    source /Users/reyhan/shail_master/services_env/bin/activate 2>/dev/null
    if python -c "import langchain_google_genai" 2>/dev/null; then
        echo "   ✅ langchain-google-genai installed"
    else
        echo "   ❌ langchain-google-genai NOT installed"
    fi
    if python -c "import fastapi" 2>/dev/null; then
        echo "   ✅ fastapi installed"
    else
        echo "   ❌ fastapi NOT installed"
    fi
    deactivate 2>/dev/null
else
    echo "   ⚠️  Cannot check packages (virtual env not accessible)"
fi

echo ""
echo "6. Checking log file..."
if [ -f "/Users/reyhan/shail_master/.cursor/debug.log" ]; then
    LOG_LINES=$(wc -l < /Users/reyhan/shail_master/.cursor/debug.log 2>/dev/null || echo "0")
    echo "   ✅ Log file exists with $LOG_LINES lines"
    if [ "$LOG_LINES" -gt 1 ]; then
        echo "   Recent entries:"
        tail -3 /Users/reyhan/shail_master/.cursor/debug.log | head -3
    fi
else
    echo "   ⚠️  Log file does not exist"
fi

echo ""
echo "=== Summary ==="
if [ "$BACKEND_COUNT" -eq 0 ]; then
    echo "❌ Backend is not running"
    echo ""
    echo "To start backend:"
    echo "  cd /Users/reyhan/shail_master"
    echo "  source services_env/bin/activate"
    echo "  cd apps/shail"
    echo "  uvicorn main:app --reload --host 0.0.0.0 --port 8000"
elif [ "$BACKEND_COUNT" -gt 1 ]; then
    echo "⚠️  Multiple backend processes - this can cause conflicts"
    echo "   Kill all and restart: pkill -9 -f 'uvicorn.*main:app'"
else
    echo "✅ Backend appears to be running"
fi
