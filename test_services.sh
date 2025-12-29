#!/bin/bash

# Quick test script to verify all services are running

echo "🧪 Testing Shail Services"
echo "========================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

test_service() {
    local name=$1
    local url=$2
    
    echo -n "Testing $name... "
    
    if curl -s "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ OK${NC}"
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        return 1
    fi
}

# Test Python services
echo "Python Services:"
echo "----------------"

test_service "Action Executor" "http://localhost:8080/health"
test_service "Vision" "http://localhost:8081/health"
test_service "RAG Retriever" "http://localhost:8082/health"
test_service "Planner" "http://localhost:8083/health"

echo ""
echo "Native Services (WebSocket - requires websocat):"
echo "-------------------------------------------------"

# Check if websocat is installed
if command -v websocat &> /dev/null; then
    echo -n "Testing CaptureService... "
    timeout 2 websocat ws://localhost:8765/capture > /dev/null 2>&1
    if [ $? -eq 124 ] || [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ OK${NC}"
    else
        echo -e "${YELLOW}⚠ Not running (Xcode required)${NC}"
    fi
    
    echo -n "Testing AccessibilityBridge... "
    timeout 2 websocat ws://localhost:8766/accessibility > /dev/null 2>&1
    if [ $? -eq 124 ] || [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ OK${NC}"
    else
        echo -e "${YELLOW}⚠ Not running (Xcode required)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ websocat not installed. Install with: brew install websocat${NC}"
    echo "   Skipping WebSocket tests..."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Test complete!"
echo ""
echo "If all Python services show ✓, you're ready to go!"
echo "Native services are optional (require Xcode)."

