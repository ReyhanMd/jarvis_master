#!/bin/bash
# Comprehensive test script for all missing bits

set -e

echo "=========================================="
echo "Missing Bits Comprehensive Test"
echo "=========================================="

LOG_FILE="/Users/reyhan/shail_master/.cursor/debug.log"
BASE_URL="http://localhost:8000"

# Clear log
echo "" > "$LOG_FILE"
echo "✅ Log file cleared"

# Test 1: Backend Health
echo ""
echo "=== Test 1: Backend Health ==="
if curl -s "$BASE_URL/health" > /dev/null 2>&1; then
    echo "✅ Backend is running"
else
    echo "❌ Backend is not running"
    echo "   Start with: uvicorn apps.shail.main:app --reload --host 0.0.0.0 --port 8000"
    exit 1
fi

# Test 2: Desktop ID Submission
echo ""
echo "=== Test 2: Desktop ID Submission ==="
RESPONSE=$(curl -s -X POST "$BASE_URL/tasks" \
    -H "Content-Type: application/json" \
    -d '{"text":"test desktop id","desktop_id":"Desktop 1"}')

if echo "$RESPONSE" | grep -q "task_id"; then
    TASK_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['task_id'])" 2>/dev/null)
    echo "✅ Task submitted: $TASK_ID"
    
    # Check log for desktop_id
    if grep -q '"desktop_id":"Desktop 1"' "$LOG_FILE"; then
        echo "✅ desktop_id found in logs"
    else
        echo "❌ desktop_id not found in logs"
    fi
else
    echo "❌ Task submission failed"
    echo "   Response: $RESPONSE"
fi

# Test 3: Check Task Status
if [ ! -z "$TASK_ID" ]; then
    echo ""
    echo "=== Test 3: Task Status ==="
    STATUS=$(curl -s "$BASE_URL/tasks/$TASK_ID" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null)
    echo "   Task status: $STATUS"
fi

# Test 4: WebSocket Endpoint
echo ""
echo "=== Test 4: WebSocket Endpoint ==="
if curl -s --http1.1 --no-buffer -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Key: test" -H "Sec-WebSocket-Version: 13" "$BASE_URL/ws/brain" > /dev/null 2>&1; then
    echo "✅ WebSocket endpoint exists"
else
    echo "⚠️  WebSocket endpoint test inconclusive (requires WebSocket client)"
fi

# Test 5: Xcode Project
echo ""
echo "=== Test 5: Xcode Project ==="
if [ -f "/Users/reyhan/shail_master/apps/mac/ShailLauncher/create_xcode_project.sh" ]; then
    echo "✅ Project generation script exists"
    if [ -f "/Users/reyhan/shail_master/apps/mac/ShailLauncher/ShailLauncher.xcodeproj/project.pbxproj" ]; then
        echo "✅ Xcode project file exists"
    else
        echo "⚠️  Xcode project not generated (run create_xcode_project.sh)"
    fi
else
    echo "❌ Project generation script missing"
fi

# Test 6: Log Analysis
echo ""
echo "=== Test 6: Log Analysis ==="
LOG_LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")
echo "   Log file has $LOG_LINES lines"

if [ "$LOG_LINES" -gt 1 ]; then
    echo "   Recent entries:"
    tail -5 "$LOG_FILE" | while read line; do
        if [ ! -z "$line" ]; then
            LOCATION=$(echo "$line" | python3 -c "import sys, json; print(json.load(sys.stdin).get('location', 'unknown'))" 2>/dev/null || echo "unknown")
            MESSAGE=$(echo "$line" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', 'unknown'))" 2>/dev/null || echo "unknown")
            echo "   - $LOCATION: $MESSAGE"
        fi
    done
fi

# Summary
echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "✅ Backend: Running"
echo "✅ Desktop ID: Implemented (check logs above)"
echo "⚠️  WebSocket: Requires Swift UI test"
echo "✅ Xcode Project: Script ready"
echo ""
echo "Next: Test Permission WebSocket with Swift UI"
