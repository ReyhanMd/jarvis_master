#!/bin/bash

# Stop all native services cleanly

echo "🛑 Stopping Native Services"
echo "============================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Kill CaptureService
if pgrep -f "CaptureService" > /dev/null; then
    echo "   Stopping CaptureService..."
    pkill -TERM -f "CaptureService" 2>/dev/null || true
    sleep 1
    
    # Force kill if still running
    if pgrep -f "CaptureService" > /dev/null; then
        echo "   Force killing CaptureService..."
        pkill -9 -f "CaptureService" 2>/dev/null || true
    fi
    echo -e "${GREEN}✅ CaptureService stopped${NC}"
else
    echo -e "${YELLOW}⚠️  CaptureService not running${NC}"
fi

# Kill AccessibilityBridge
if pgrep -f "AccessibilityBridge" > /dev/null; then
    echo "   Stopping AccessibilityBridge..."
    pkill -TERM -f "AccessibilityBridge" 2>/dev/null || true
    sleep 1
    
    # Force kill if still running
    if pgrep -f "AccessibilityBridge" > /dev/null; then
        echo "   Force killing AccessibilityBridge..."
        pkill -9 -f "AccessibilityBridge" 2>/dev/null || true
    fi
    echo -e "${GREEN}✅ AccessibilityBridge stopped${NC}"
else
    echo -e "${YELLOW}⚠️  AccessibilityBridge not running${NC}"
fi

# Clean up temporary scripts
echo ""
echo "🧹 Cleaning up temporary scripts..."
rm -f /tmp/capture_service_*.sh 2>/dev/null || true
rm -f /tmp/accessibility_bridge_*.sh 2>/dev/null || true
echo -e "${GREEN}✅ Cleanup complete${NC}"

echo ""
echo "✅ All native services stopped"
