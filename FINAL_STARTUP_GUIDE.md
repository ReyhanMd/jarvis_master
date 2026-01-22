# Final Startup Guide - Step by Step

## Current Status
- ✅ Port 8000 is free
- ✅ Virtual environment exists
- ✅ Packages installed
- ❌ Backend not running

## Why Backend Might Not Start

The backend might be failing to start due to:
1. Import errors
2. Missing dependencies
3. Configuration issues
4. Port conflicts (though port is free now)

## Step-by-Step Startup

### Step 1: Test Imports First

Before starting the server, test if imports work:

```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
python -c "from main import app; print('✅ Imports OK')"
```

**If this fails**, you'll see the error. Fix the error before proceeding.

### Step 2: Start Backend

**Option A: With error capture (recommended)**
```bash
cd /Users/reyhan/shail_master
./START_BACKEND_WITH_ERRORS.sh
```

**Option B: Manual start**
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd apps/shail
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 3: Watch for Errors

When you start the backend, watch for:
- ✅ "Application startup complete" = Success!
- ❌ Import errors = Missing packages or code issues
- ❌ Port errors = Something else using port 8000
- ❌ Configuration errors = Missing .env or settings

### Step 4: If Backend Starts Successfully

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 5: Verify in New Terminal

```bash
# Test health
curl http://localhost:8000/health
# Should return: {"status":"ok","service":"shail"}

# Test WebSocket
cd /Users/reyhan/shail_master
source services_env/bin/activate
python test_websocket.py
# Should show: "WebSocket connected successfully!"
```

## Common Errors and Fixes

### Error: "ModuleNotFoundError"
**Fix**: Install missing package
```bash
source services_env/bin/activate
pip install <missing-package>
```

### Error: "Port already in use"
**Fix**: Kill process using port
```bash
./fix_port_8000.sh
```

### Error: "Import error"
**Fix**: Check Python path and virtual environment
```bash
which python  # Should show services_env/bin/python
```

### Error: "Configuration error"
**Fix**: Check .env file exists
```bash
ls -la .env
# If missing, create it with required variables
```

## Complete Startup Sequence

1. **Terminal 1**: Start backend
   ```bash
   cd /Users/reyhan/shail_master
   ./START_BACKEND_WITH_ERRORS.sh
   ```
   - Watch for errors
   - Wait for "Application startup complete"

2. **Terminal 2**: Verify backend
   ```bash
   curl http://localhost:8000/health
   python test_websocket.py
   ```

3. **Terminal 3**: Start worker
   ```bash
   cd /Users/reyhan/shail_master
   source services_env/bin/activate
   python -m shail.workers.task_worker
   ```

4. **Terminal 4**: Start Swift UI
   ```bash
   cd /Users/reyhan/shail_master/apps/mac/ShailUI
   swift run
   ```
   Then press **Option+S**

## If Backend Won't Start

1. Run diagnostics: `./diagnose.sh`
2. Check for errors in the startup output
3. Test imports: `python -c "from apps.shail.main import app"`
4. Check logs: `cat /Users/reyhan/shail_master/.cursor/debug.log`
5. Share the error message for help

## Success Indicators

✅ Backend shows "Application startup complete"
✅ Health check returns `{"status":"ok","service":"shail"}`
✅ WebSocket test shows "WebSocket connected successfully!"
✅ Worker starts without errors
✅ Swift UI panel appears when you press Option+S
