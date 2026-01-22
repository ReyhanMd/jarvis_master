#!/bin/bash
# Start backend with error capture

cd /Users/reyhan/shail_master || exit 1

echo "=== Starting Backend with Error Capture ==="
echo ""

# Kill any existing backends
echo "1. Stopping old processes..."
pkill -f "uvicorn.*main:app" 2>/dev/null
sleep 1

# Activate virtual environment
echo "2. Activating virtual environment..."
source services_env/bin/activate || {
    echo "❌ Failed to activate services_env"
    exit 1
}

# Test imports first
echo "3. Testing imports..."
cd apps/shail
python -c "from main import app" 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Import failed - check errors above"
    exit 1
fi
echo "✅ Imports successful"

# Start backend with error output
echo ""
echo "4. Starting backend..."
echo "   (Errors will be shown below)"
echo "   Press Ctrl+C to stop"
echo ""

# Capture both stdout and stderr
uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | tee /tmp/backend_output.log
