#!/bin/bash

# Shail Worker Startup Script
# This script starts the worker - it will automatically load .env file if it exists

# Navigate to project root first
cd "$(dirname "$0")"

# Ensure PYTHONPATH includes project root (critical for shail imports)
export PYTHONPATH="$PWD:$PYTHONPATH"

# Verify shail directory exists
if [ ! -d "shail" ]; then
    echo "❌ ERROR: shail directory not found in $PWD"
    exit 1
fi

# Verify we can import shail using the same method the worker uses
if python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())
try:
    import shail
    sys.exit(0)
except ImportError:
    sys.exit(1)
" 2>/dev/null; then
    echo "✓ shail module importable"
else
    echo "⚠ Warning: shail module may not be importable"
    echo "  Current directory: $PWD"
    echo "  PYTHONPATH: $PYTHONPATH"
    echo "  Attempting to continue anyway..."
fi

# Check if .env file exists
if [ -f ".env" ]; then
    echo "✓ Found .env file - configuration will be loaded automatically"
else
    echo "⚠ Warning: .env file not found"
    echo "  Create .env file with your GEMINI_API_KEY (see .env.example)"
    echo "  Or export GEMINI_API_KEY in this terminal session"
    echo ""
fi

# Start the worker (settings.py will automatically load .env file)
echo "Starting Shail Worker..."
echo "Project root: $PWD"

# Use the virtual environment's Python if available, otherwise use system Python
if [ -f "jarvis-env/bin/python" ]; then
    PYTHON_CMD="jarvis-env/bin/python"
    echo "Using virtual environment Python: $PYTHON_CMD"
else
    PYTHON_CMD="python3"
    echo "Using system Python: $PYTHON_CMD"
fi

# Check if dependencies are installed (NOW that PYTHON_CMD is defined)
if ! $PYTHON_CMD -c "import redis" 2>/dev/null; then
    echo ""
    echo "⚠ WARNING: Missing dependencies!"
    echo "  Run: pip install -r requirements.txt"
    echo "  Or see INSTALL_DEPENDENCIES.md for details"
    echo ""
fi

# Run using the direct runner script (handles path setup correctly)
# Use -u flag for unbuffered output (critical for background processes)
$PYTHON_CMD -u run_worker.py

