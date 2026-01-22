# Missing Bits Verification Guide

This guide helps verify that all three missing pieces are working correctly.

## Implementation Status

### ✅ 1. Permission WebSocket Notifications
- **Backend**: `shail/safety/permission_manager.py` - Broadcasts permission requests
- **Frontend**: `apps/mac/ShailUI/BackendWebSocketClient.swift` - Receives events
- **UI**: `apps/mac/ShailUI/QuickPopupView.swift` - Shows modal automatically

### ✅ 2. Desktop ID Wiring
- **Model**: `shail/core/types.py` - Added `desktop_id` field
- **Service**: `apps/mac/ShailUI/TaskService.swift` - Includes desktop_id in submission
- **Graph**: `shail/orchestration/graph.py` - Includes desktop_id in initial state

### ✅ 3. Xcode Project Generation
- **Script**: `apps/mac/ShailLauncher/create_xcode_project.sh` - Generates project
- **Project**: `apps/mac/ShailLauncher/ShailLauncher.xcodeproj` - Ready to build

## Verification Steps

### Step 1: Verify Xcode Project
```bash
cd /Users/reyhan/shail_master/apps/mac/ShailLauncher
./create_xcode_project.sh
open ShailLauncher.xcodeproj
# In Xcode: ⌘+B to build
```
**Expected**: Project builds successfully ✅

### Step 2: Start Services
```bash
# Terminal 1: Backend
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Worker
cd /Users/reyhan/shail_master
source services_env/bin/activate
python -m shail.workers.task_worker

# Terminal 3: Swift UI
cd /Users/reyhan/shail_master/apps/mac/ShailUI
swift run
```

### Step 3: Show ShailUI Panel
- Press **Option+S** to show the panel (hotkey)
- Or click the app icon in the dock
- The panel should appear in bottom-right corner

### Step 4: Verify WebSocket Connection
**Check Terminal 3 (Swift UI)** for:
```
🔍 [DEBUG] Attempting WebSocket connection to ws://localhost:8000/ws/brain
🔍 [DEBUG] Log written to /Users/reyhan/shail_master/.cursor/debug.log
🔌 Connected to backend WebSocket
```

**Check Terminal 1 (Backend)** for:
```
🔌 WebSocket client connected. Total: 1
```

**Check log file**:
```bash
cat /Users/reyhan/shail_master/.cursor/debug.log | grep "WebSocket"
```

### Step 5: Test Desktop ID
1. In ShailUI panel, type a query (e.g., "hello")
2. Press Enter or click submit button
3. **Check Terminal 3** for: `🔍 [DEBUG] TaskService: Submitting task with desktopId=Desktop 1`
4. **Check Terminal 1** for: `🔍 [DEBUG] Task submission received: desktop_id=Desktop 1`
5. **Check Terminal 2** for: `Processing task from queue` with desktop_id
6. **Check log**:
```bash
cat /Users/reyhan/shail_master/.cursor/debug.log | grep "desktop"
```

**Expected**: `desktop_id` should be "Desktop 1" (not null) ✅

### Step 6: Test Permission WebSocket
1. Submit a task that requires permission (e.g., "open Calculator")
2. **Check Terminal 1** for: `🔍 [DEBUG] Permission request created: ...`
3. **Check Terminal 1** for: `Broadcasting event` with `event_type: permission_requested`
4. **Check Terminal 3** for: `Received event` with `permission_requested`
5. **Check UI**: Permission modal should appear automatically
6. **Check log**:
```bash
cat /Users/reyhan/shail_master/.cursor/debug.log | grep "permission"
```

**Expected**: Permission modal appears automatically ✅

## Troubleshooting

### Issue: Log file is empty
**Possible causes**:
- Services aren't running
- Swift UI isn't running
- Panel is hidden (press Option+S)
- Logging code isn't executing

**Fix**: Ensure all services are running and panel is visible

### Issue: WebSocket shows 0 connections
**Possible causes**:
- Backend not running
- Swift UI not connecting
- Network issue

**Fix**: 
1. Verify backend is running: `curl http://localhost:8000/health`
2. Check Swift UI console for connection errors
3. Verify WebSocket URL: `ws://localhost:8000/ws/brain`

### Issue: desktop_id is null
**Possible causes**:
- TaskService not being called
- Request not reaching backend
- desktop_id not in request dict

**Fix**:
1. Check Terminal 3 for TaskService logs
2. Check Terminal 1 for submit_task logs
3. Verify desktopManager.activeDesktop is set

### Issue: Permission modal doesn't appear
**Possible causes**:
- WebSocket not connected
- Event not being received
- onChange not firing

**Fix**:
1. Verify WebSocket connection (check logs)
2. Check if permission_requested event is broadcast
3. Verify onChange handler is set up correctly

## Quick Test Script

```bash
#!/bin/bash
# Quick verification script

echo "=== Testing Missing Bits ==="

# Test 1: Xcode Project
echo "1. Testing Xcode project..."
cd /Users/reyhan/shail_master/apps/mac/ShailLauncher
./create_xcode_project.sh
if [ -f "ShailLauncher.xcodeproj/project.pbxproj" ]; then
    echo "✅ Xcode project exists"
else
    echo "❌ Xcode project missing"
fi

# Test 2: Check backend health
echo "2. Testing backend..."
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ Backend is running"
else
    echo "❌ Backend is not running"
fi

# Test 3: Check WebSocket endpoint
echo "3. Testing WebSocket endpoint..."
# WebSocket test would require a client - skip for now
echo "⚠️  WebSocket test requires manual verification"

# Test 4: Check log file
echo "4. Checking log file..."
if [ -f "/Users/reyhan/shail_master/.cursor/debug.log" ]; then
    LINE_COUNT=$(wc -l < /Users/reyhan/shail_master/.cursor/debug.log)
    echo "✅ Log file exists with $LINE_COUNT lines"
    if [ "$LINE_COUNT" -gt 1 ]; then
        echo "   Recent entries:"
        tail -5 /Users/reyhan/shail_master/.cursor/debug.log
    fi
else
    echo "❌ Log file missing"
fi

echo "=== Done ==="
```

## Success Criteria

- ✅ Xcode project builds successfully
- ✅ WebSocket connection established (check logs for "WebSocket client connected")
- ✅ desktop_id included in task submissions (check logs for "desktop_id": "Desktop 1")
- ✅ Permission modal appears automatically when permission is requested
- ✅ All debug logs are written to `.cursor/debug.log`

## Next Steps

Once all tests pass:
1. Remove debug instrumentation (keep it for now until verified)
2. Document the final implementation
3. Create integration tests
4. Update user documentation
