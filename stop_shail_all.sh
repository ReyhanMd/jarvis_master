#!/bin/bash

# 🛑 Shail Unified Stop Script
# Stops ALL Shail services

echo "🛑 Stopping Shail Services..."
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Stop native services
echo "🎥 Stopping CaptureService..."
pkill -f "CaptureService" 2>/dev/null && echo -e "${GREEN}✅ Stopped${NC}" || echo -e "${YELLOW}⚠️  Not running${NC}"

echo "♿ Stopping AccessibilityBridge..."
pkill -f "AccessibilityBridge" 2>/dev/null && echo -e "${GREEN}✅ Stopped${NC}" || echo -e "${YELLOW}⚠️  Not running${NC}"

# Stop Python services
echo ""
echo "🐍 Stopping Python services..."
pkill -f "services/ui_twin/service.py" 2>/dev/null && echo -e "${GREEN}✅ UI Twin stopped${NC}" || true
pkill -f "services/action_executor/service.py" 2>/dev/null && echo -e "${GREEN}✅ Action Executor stopped${NC}" || true
pkill -f "services/vision/service.py" 2>/dev/null && echo -e "${GREEN}✅ Vision stopped${NC}" || true
pkill -f "services/rag_retriever/service.py" 2>/dev/null && echo -e "${GREEN}✅ RAG Retriever stopped${NC}" || true
pkill -f "services/planner/service.py" 2>/dev/null && echo -e "${GREEN}✅ Planner stopped${NC}" || true

# Stop Shail core
echo ""
echo "🚀 Stopping Shail core services..."
pkill -f "task_worker" 2>/dev/null && echo -e "${GREEN}✅ Task Worker stopped${NC}" || true
pkill -f "uvicorn apps.shail.main:app" 2>/dev/null && echo -e "${GREEN}✅ Shail API stopped${NC}" || true
pkill -f "npm run dev" 2>/dev/null && echo -e "${GREEN}✅ Shail UI stopped${NC}" || true

# Stop Redis (optional - comment out if you want Redis to keep running)
echo ""
read -p "Stop Redis? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    pkill -f "redis-server" 2>/dev/null && echo -e "${GREEN}✅ Redis stopped${NC}" || echo -e "${YELLOW}⚠️  Redis not running${NC}"
fi

echo ""
echo "✅ All services stopped!"

