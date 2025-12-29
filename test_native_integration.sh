#!/bin/bash

# Integration test script for native services

echo "🧪 Testing Native Services Integration"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0

# Test 1: Check if services are running
test_service_running() {
    local service=$1
    echo -n "Testing $service is running... "
    
    if pgrep -f "$service" > /dev/null; then
        echo -e "${GREEN}✓${NC}"
        return 0
    else
        echo -e "${RED}✗${NC}"
        echo "   $service is not running"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Test 2: Check if ports are listening
test_port_listening() {
    local port=$1
    local service=$2
    echo -n "Testing port $port is listening... "
    
    if lsof -ti:$port > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        return 0
    else
        echo -e "${RED}✗${NC}"
        echo "   Port $port is not listening"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Test 2b: Test HTTP health check endpoint
test_health_endpoint() {
    local port=$1
    local service=$2
    echo -n "Testing health endpoint for $service... "
    
    if command -v curl &> /dev/null; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health 2>/dev/null)
        if [ "$HTTP_CODE" = "200" ]; then
            echo -e "${GREEN}✓${NC}"
            return 0
        else
            echo -e "${RED}✗${NC} (HTTP $HTTP_CODE)"
            FAILED=$((FAILED + 1))
            return 1
        fi
    else
        echo -e "${YELLOW}⚠${NC} (curl not installed)"
        return 0
    fi
}

# Test 3: Test WebSocket connection
test_websocket_connection() {
    local port=$1
    local path=$2
    local service=$3
    echo -n "Testing WebSocket connection to $service... "
    
    if command -v websocat &> /dev/null; then
        timeout 2 websocat "ws://localhost:$port$path" > /dev/null 2>&1
        if [ $? -eq 124 ] || [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC}"
            return 0
        else
            echo -e "${RED}✗${NC}"
            echo "   Cannot connect to ws://localhost:$port$path"
            FAILED=$((FAILED + 1))
            return 1
        fi
    else
        echo -e "${YELLOW}⚠${NC} (websocat not installed)"
        return 0
    fi
}

# Run tests
echo "1. Process Tests"
echo "----------------"
test_service_running "CaptureService"
test_service_running "AccessibilityBridge"
echo ""

echo "2. Port Tests"
echo "-------------"
test_port_listening 8765 "CaptureService (WebSocket)"
test_port_listening 8767 "CaptureService (Health)"
test_port_listening 8766 "AccessibilityBridge (WebSocket)"
test_port_listening 8768 "AccessibilityBridge (Health)"
echo ""

echo "2b. Health Check Tests"
echo "----------------------"
test_health_endpoint 8767 "CaptureService"
test_health_endpoint 8768 "AccessibilityBridge"
echo ""

echo "3. WebSocket Tests"
echo "------------------"
test_websocket_connection 8765 "/capture" "CaptureService"
test_websocket_connection 8766 "/accessibility" "AccessibilityBridge"
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED test(s) failed${NC}"
    exit 1
fi

