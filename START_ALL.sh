#!/bin/bash

# Shail Complete Startup Script
# This script starts all 4 components of Shail
# Note: You'll need to run each in separate terminals

echo "=========================================="
echo "Shail Startup Guide"
echo "=========================================="
echo ""
echo "You need to run these commands in 4 separate terminals:"
echo ""
echo "TERMINAL 1 (Redis):"
echo "  redis-server"
echo ""
echo "TERMINAL 2 (Worker):"
echo "  cd /Users/reyhan/shail_master"
echo "  export GEMINI_API_KEY=\"AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI\""
echo "  python -m shail.workers.task_worker"
echo ""
echo "TERMINAL 3 (API):"
echo "  cd /Users/reyhan/shail_master"
echo "  uvicorn apps.shail.main:app --reload"
echo ""
echo "TERMINAL 4 (UI):"
echo "  cd /Users/reyhan/shail_master/apps/shail-ui"
echo "  npm install  # First time only"
echo "  npm run dev"
echo ""
echo "Then open: http://localhost:5173"
echo ""
echo "=========================================="

