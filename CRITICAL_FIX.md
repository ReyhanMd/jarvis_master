# Critical Fix: WebSocket 404 Error

## Problem Identified

**Root Cause**: The backend is running **OLD CODE** that doesn't have the WebSocket route registered.

**Evidence**:
- ✅ Route exists in code: `/ws/brain` is defined in `apps/shail/main.py`
- ❌ Running backend returns: HTTP 404 for `/ws/brain`
- ⚠️ Two backend processes running (conflicting)

## Solution

### Step 1: Kill ALL Backend Processes

```bash
# Kill both processes
kill 10673 18049

# Wait a moment
sleep 2

# Force kill if still running
pkill -9 -f "uvicorn.*main:app"

# Verify they're gone
ps aux | grep uvicorn | grep -v grep
# Should show nothing
```

### Step 2: Verify Port is Free

```bash
lsof -i :8000
# Should show nothing (or only unrelated processes)
```

### Step 3: Start Backend with NEW Code (Terminal 1)

**CRITICAL**: Make sure you're in the right directory and using the right virtual environment:

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Watch for**:
- "Application startup complete"
- No errors about missing modules
- Check that it says "Shail Service" (not old version)

### Step 4: Verify WebSocket Route is Registered

In a NEW terminal (while backend is running):

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
python -c "from apps.shail.main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print('WebSocket routes:'); [print(f'  {r}') for r in routes if 'ws' in r or 'brain' in r]"
```

**Expected**: Should show `/ws/brain`

### Step 5: Test WebSocket Connection

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
pip install websockets  # If not installed
python test_websocket.py
```

**Expected**: 
- ✅ "WebSocket connected successfully!"
- ✅ "Ping/pong working!"

**NOT**: ❌ "HTTP 404"

### Step 6: Check Logs

```bash
cat /Users/reyhan/shail_master/.cursor/debug.log
```

**Expected**: Should see WebSocket connection logs if connection succeeds

## Why This Happened

The backend processes were started **before** the WebSocket route was added to the code. Even with `--reload`, sometimes uvicorn doesn't pick up route changes properly, especially if:
- Multiple instances are running
- The code was modified while the server was running
- There are import errors that prevent reload

## Prevention

Always:
1. Kill old processes before starting new ones
2. Verify only ONE backend is running
3. Check that routes are registered after startup
4. Test the endpoint immediately after starting

## Summary

**Issue**: Backend running old code without WebSocket route
**Fix**: Kill all processes, restart with new code
**Test**: Verify route exists, test connection
