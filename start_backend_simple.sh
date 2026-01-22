#!/bin/bash
# Simple one-command backend starter

cd /Users/reyhan/shail_master || exit 1

# Kill any existing backends
echo "Stopping old backend processes..."
pkill -f "uvicorn.*main:app" 2>/dev/null
sleep 1

# Activate virtual environment
echo "Activating virtual environment..."
source services_env/bin/activate || {
    echo "❌ Failed to activate services_env"
    echo "   Create it with: python3 -m venv services_env"
    exit 1
}

# Check if we're in the right directory
if [ ! -f "apps/shail/main.py" ]; then
    echo "❌ Cannot find apps/shail/main.py"
    echo "   Make sure you're in the shail_master directory"
    exit 1
fi

# Start backend
echo "Starting backend..."
echo "   Press Ctrl+C to stop"
echo ""
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000
