# Debug Fixes Applied

## Issue 1: Missing Package ✅ FIXED

**Problem**: `ModuleNotFoundError: No module named 'langchain_google_genai'`

**Solution**: Installed the missing package:
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
pip install langchain-google-genai
```

**Status**: ✅ **FIXED** - Package installed successfully

**Next Step**: Restart the worker (Terminal 2)

---

## Issue 2: WebSocket Connection Error ⚠️ NEEDS BACKEND RESTART

**Problem**: Swift UI getting "There was a bad response from the server" when connecting to `ws://localhost:8000/ws/brain`

**Root Cause**: 
- The WebSocket route `/ws/brain` is registered correctly
- The backend might need to be restarted to pick up the WebSocket endpoint
- There might be multiple backend instances running

**Solution**:
1. Stop the current backend (Ctrl+C in Terminal 1)
2. Restart the backend:
   ```bash
   cd /Users/reyhan/shail_master
   source services_env/bin/activate
   cd apps/shail
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

**Status**: ⚠️ **NEEDS RESTART** - Route exists, but backend needs restart

---

## Verification Steps

### 1. Test Worker (Terminal 2)
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
python -m shail.workers.task_worker
```

**Expected**: Should start without errors (no ModuleNotFoundError)

### 2. Test Backend WebSocket
After restarting backend, test WebSocket:
```bash
# Check if route exists
curl http://localhost:8000/health

# Test WebSocket (should connect)
# Use a WebSocket client or check Swift UI logs
```

### 3. Test Swift UI Connection
1. Start Swift UI: `cd apps/mac/ShailUI && swift run`
2. Press Option+S to show panel
3. Check Terminal 3 for: `🔌 Connected to backend WebSocket` (no errors)
4. Check Terminal 1 for: `🔌 WebSocket client connected. Total: 1`

---

## Summary

✅ **Issue 1 Fixed**: Package installed
⚠️ **Issue 2**: Backend needs restart to fix WebSocket

**Action Required**:
1. Restart backend (Terminal 1)
2. Restart worker (Terminal 2) - should work now
3. Test Swift UI connection (Terminal 3)
