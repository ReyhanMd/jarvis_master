#!/bin/bash

# Health check script for native services

echo "🏥 Native Services Health Check"
echo "==============================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check CaptureService
echo "📹 CaptureService"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if pgrep -f "CaptureService" > /dev/null; then
    PID=$(pgrep -f "CaptureService" | head -1)
    echo -e "   Status: ${GREEN}Running${NC} (PID: $PID)"
    
    if lsof -ti:8765 > /dev/null 2>&1; then
        echo -e "   WebSocket (8765): ${GREEN}Listening${NC}"
    else
        echo -e "   WebSocket (8765): ${RED}Not listening${NC}"
    fi
    
    if lsof -ti:8767 > /dev/null 2>&1; then
        echo -e "   Health Check (8767): ${GREEN}Listening${NC}"
        if command -v curl &> /dev/null; then
            HEALTH=$(curl -s http://localhost:8767/health 2>/dev/null | head -1)
            if [ -n "$HEALTH" ]; then
                echo -e "   Health Status: ${GREEN}Healthy${NC}"
            fi
        fi
    else
        echo -e "   Health Check (8767): ${RED}Not listening${NC}"
    fi
else
    echo -e "   Status: ${RED}Not running${NC}"
    echo -e "   WebSocket (8765): ${RED}Not listening${NC}"
    echo -e "   Health Check (8767): ${RED}Not listening${NC}"
fi
echo ""

# Check AccessibilityBridge
echo "♿ AccessibilityBridge"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if pgrep -f "AccessibilityBridge" > /dev/null; then
    PID=$(pgrep -f "AccessibilityBridge" | head -1)
    echo -e "   Status: ${GREEN}Running${NC} (PID: $PID)"
    
    if lsof -ti:8766 > /dev/null 2>&1; then
        echo -e "   WebSocket (8766): ${GREEN}Listening${NC}"
    else
        echo -e "   WebSocket (8766): ${RED}Not listening${NC}"
    fi
    
    if lsof -ti:8768 > /dev/null 2>&1; then
        echo -e "   Health Check (8768): ${GREEN}Listening${NC}"
        if command -v curl &> /dev/null; then
            HEALTH=$(curl -s http://localhost:8768/health 2>/dev/null | head -1)
            if [ -n "$HEALTH" ]; then
                echo -e "   Health Status: ${GREEN}Healthy${NC}"
            fi
        fi
    else
        echo -e "   Health Check (8768): ${RED}Not listening${NC}"
    fi
else
    echo -e "   Status: ${RED}Not running${NC}"
    echo -e "   WebSocket (8766): ${RED}Not listening${NC}"
    echo -e "   Health Check (8768): ${RED}Not listening${NC}"
fi
echo ""

# Check permissions
echo "🔐 Permissions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}   Note: Check System Settings → Privacy & Security${NC}"
echo "   - Screen Recording: Should have CaptureService enabled"
echo "   - Accessibility: Should have AccessibilityBridge enabled"
echo ""

# Port usage details
echo "📊 Port Usage"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Port 8765 (CaptureService):"
lsof -ti:8765 2>/dev/null | while read pid; do
    ps -p $pid -o comm= 2>/dev/null | xargs echo "   - Process:"
done || echo "   - No process found"

echo "Port 8766 (AccessibilityBridge):"
lsof -ti:8766 2>/dev/null | while read pid; do
    ps -p $pid -o comm= 2>/dev/null | xargs echo "   - Process:"
done || echo "   - No process found"
echo ""

echo "✅ Health check complete"

