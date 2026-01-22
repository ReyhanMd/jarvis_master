# Final Debug Instructions

## Current Status

- ✅ **Package installed**: `langchain-google-genai` is installed
- ✅ **Logging added**: Comprehensive WebSocket logging in place
- ⚠️ **Multiple backends**: 4 processes still running on port 8000
- ⚠️ **Empty logs**: Backend hasn't been restarted with new code

## Critical Issue: Multiple Backend Instances

There are **4 Python processes** listening on port 8000:
- PID 10673: Python 3.13 (homebrew)
- PID 18049: jarvis-env
- PID 19574: Another instance
- PID 19578: Another instance

**This is causing conflicts!** Only ONE backend should be running.

## Solution: Clean Restart

### Step 1: Kill All Backend Processes

```bash
# Run the restart script
cd /Users/reyhan/shail_master
./restart_backend.sh

# Or manually:
pkill -f "uvicorn.*main:app"
sleep 2
pkill -9 -f "uvicorn.*main:app"  # Force kill if needed
```

### Step 2: Verify Port is Free

```bash
lsof -i :8000
# Should show nothing (or only unrelated processes)
```

### Step 3: Start Backend (Terminal 1)

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Watch for**: "Application startup complete"

### Step 4: Test WebSocket (New Terminal)

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
pip install websockets  # If not installed
python test_websocket.py
```

**Expected**: 
- ✅ WebSocket connected successfully!
- ✅ Ping/pong working!

### Step 5: Test Worker (Terminal 2)

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
python -m shail.workers.task_worker
```

**Expected**: Should start without errors

### Step 6: Test Swift UI (Terminal 3)

```bash
cd /Users/reyhan/shail_master/apps/mac/ShailUI
swift run
```

Then:
1. Press **Option+S** to show panel
2. Check Terminal 1 for WebSocket logs
3. Check Terminal 3 for connection status

## Expected Log Flow

When WebSocket connects, you should see in `/Users/reyhan/shail_master/.cursor/debug.log`:

1. `main.py:websocket_brain: WebSocket route called`
2. `websocket_server.py:websocket_endpoint: WebSocket endpoint called`
3. `websocket_server.py:connect: WebSocket client connected`
4. `websocket_server.py:websocket_endpoint: WebSocket accepted, entering message loop`

## Troubleshooting

### If WebSocket test fails:
- Check backend is running: `curl http://localhost:8000/health`
- Check only one backend: `ps aux | grep uvicorn`
- Check logs: `cat /Users/reyhan/shail_master/.cursor/debug.log`

### If worker fails:
- Verify package: `pip list | grep langchain-google-genai`
- Check virtual environment: `which python` (should be services_env)

### If Swift UI fails:
- Check backend logs for WebSocket connection attempts
- Verify WebSocket URL: `ws://localhost:8000/ws/brain`
- Check Terminal 3 for error messages

## Summary

**The main issue**: Multiple backend instances are conflicting.

**The fix**: Kill all old processes and restart cleanly.

**The test**: Use `test_websocket.py` to verify the endpoint works.
