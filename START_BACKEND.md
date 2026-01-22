# Start Backend - Step by Step

## Current Status
- ✅ Old processes killed
- ✅ Log file cleared
- ❌ Backend not running (connection refused)

## Start Backend (Terminal 1)

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**What to watch for:**
- "Application startup complete"
- "Uvicorn running on http://0.0.0.0:8000"
- No import errors
- Should see "Shail Service" in the startup message

**Keep this terminal open and visible!**

## Verify Backend is Running

In a NEW terminal:

```bash
# Test health endpoint
curl http://localhost:8000/health

# Should return: {"status":"ok","service":"shail"}
```

## Test WebSocket Route

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
python test_websocket.py
```

**Expected**: 
- ✅ "WebSocket connected successfully!"
- ✅ "Ping/pong working!"

**NOT**: ❌ "Connect call failed" or ❌ "HTTP 404"

## If You See Errors

### Import Errors
- Make sure you're in `services_env` virtual environment
- Check: `which python` should show `services_env/bin/python`

### Port Already in Use
- Kill any remaining processes: `pkill -9 -f uvicorn`
- Wait 2 seconds
- Try again

### Module Not Found
- Install dependencies: `pip install -r requirements.txt`
- Make sure you're in the right directory

## Next Steps After Backend Starts

1. **Test Worker** (Terminal 2):
   ```bash
   cd /Users/reyhan/shail_master
   source services_env/bin/activate
   python -m shail.workers.task_worker
   ```

2. **Test Swift UI** (Terminal 3):
   ```bash
   cd /Users/reyhan/shail_master/apps/mac/ShailUI
   swift run
   ```
   Then press **Option+S** to show panel

3. **Check Logs**:
   ```bash
   cat /Users/reyhan/shail_master/.cursor/debug.log
   ```
