# Starting Shail - Complete Guide

This guide will help you start all four components of the Shail system.

## Prerequisites

1. **Node.js and npm** - Required for the React UI
   - Check if installed: `node --version` and `npm --version`
   - If not installed, download from: https://nodejs.org/

2. **Redis** - Required for task queue
   - Check if installed: `redis-server --version`
   - Install on macOS: `brew install redis`

3. **Python 3** - Required for backend
   - Should already be installed since you've been running Python scripts

4. **Configuration** - REQUIRED
   
   **Option 1: .env File (Recommended - Easiest)**
   - Create a `.env` file in the project root
   - Copy `.env.example` to `.env`: `cp .env.example .env`
   - Edit `.env` and add your `GEMINI_API_KEY`
   - Shail will automatically load this file on startup
   
   **Option 2: Terminal Export (Alternative)**
   - Export `GEMINI_API_KEY` in your terminal: `export GEMINI_API_KEY="your-key"`
   - This works but must be done in each new terminal session
   
   **Other Optional Variables:**
   - `REDIS_URL` - Default: `redis://localhost:6379/0`
   - `SHAIL_SQLITE` - Path to SQLite database (auto-created if not set)

## Starting All Services

Open **4 separate terminal windows** and run the commands below:

---

### Terminal 1: Redis Server

```bash
redis-server
```

**Expected output:** You should see Redis starting up. Leave this running.

**To verify:** In another terminal, run `redis-cli ping` - should return `PONG`

---

### Terminal 2: Shail Worker

**Method 1: Using .env File (Recommended)**

First, create your `.env` file (if you haven't already):
```bash
cd /Users/reyhan/jarvis_master
cp .env.example .env
# Then edit .env and add your GEMINI_API_KEY
```

Then start the worker:
```bash
cd /Users/reyhan/jarvis_master
python -m shail.workers.task_worker
```

**OR use the helper script:**
```bash
cd /Users/reyhan/jarvis_master
./start_worker.sh
```

**Method 2: Using Terminal Export (Alternative)**

If you prefer to export in terminal instead of using .env file:
```bash
cd /Users/reyhan/jarvis_master

# Set your Gemini API key (REQUIRED - must be UPPERCASE)
export GEMINI_API_KEY="AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI"

# Optional: Set PYTHONPATH to help with imports
export PYTHONPATH="$PWD:$PYTHONPATH"

# Now run the worker
python -m shail.workers.task_worker
```

**Note:** The `.env` file method is preferred because:
- ✅ Works automatically (no need to export each time)
- ✅ Works in packaged apps
- ✅ One-time setup

**Expected output:**
```
[Worker] Starting task worker (polling queue 'shail_tasks')...
[Worker] Poll timeout: 5s
```

**What it does:** This worker picks up tasks from the Redis queue and executes them. It requires the `GEMINI_API_KEY` environment variable to be set, otherwise it will crash with a `KeyError: 'gemini_api_key'`.

**Note:** You must set `GEMINI_API_KEY` in this terminal BEFORE running the worker, or it will fail to initialize the Master Planner.

---

### Terminal 3: Shail API (FastAPI)

```bash
cd /Users/reyhan/jarvis_master
uvicorn apps.shail.main:app --reload
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**What it does:** This is the main API server that handles HTTP requests from the UI.

**API Documentation:** Visit http://localhost:8000/docs for interactive API docs

---

### Terminal 4: Shail UI (React)

```bash
cd /Users/reyhan/jarvis_master/apps/shail-ui

# First time only: Install dependencies
npm install

# Start the development server
npm run dev
```

**Expected output:**
```
VITE v5.x.x  ready in xxx ms

➜  Local:   http://localhost:5173/
➜  Network: use --host to expose
```

**What it does:** This is the React dashboard UI (the "cockpit").

**Open in browser:** Navigate to the URL shown (usually http://localhost:5173)

---

## Testing the System

### Test 1: Safe Command (Read-only)

1. In the browser, type in the chat input:
   ```
   list all files in the workspace
   ```

2. Click "Send"

3. Watch the task card appear on the right side:
   - Status will change: `queued` → `running` → `completed`
   - You'll see the result in the task card

### Test 2: Dangerous Command (Requires Approval)

1. Type in the chat input:
   ```
   run npm install in the workspace
   ```

2. Click "Send"

3. Watch what happens:
   - Task appears with status `queued`
   - Status changes to `running`
   - **Permission Modal pops up automatically**
   - Status shows `awaiting_approval`

4. In the modal, you'll see:
   - **Tool:** `run_command`
   - **Details:** The command that will be executed
   - **Rationale:** Why this requires permission

5. Click **"Approve"**

6. Watch the status update:
   - `awaiting_approval` → `queued` → `running` → `completed`
   - The task completes after your approval

### Test 3: Code Generation

Try:
```
create a simple Python hello world script
```

The CodeAgent will generate code and save it to a file.

---

## Troubleshooting

### Issue: npm command not found

**Solution:** Install Node.js from https://nodejs.org/

Verify installation:
```bash
node --version  # Should show v18.x.x or higher
npm --version   # Should show 9.x.x or higher
```

### Issue: redis-server command not found

**Solution:** Install Redis:
```bash
# macOS
brew install redis

# Linux
sudo apt-get install redis-server  # Ubuntu/Debian
```

### Issue: Python module not found errors

**Solution:** Make sure you're in the project root and Python can find the modules:
```bash
cd /Users/reyhan/jarvis_master
python -m shail.workers.task_worker
```

### Issue: Port 8000 already in use

**Solution:** Stop any other service on port 8000, or change the port:
```bash
uvicorn apps.shail.main:app --reload --port 8001
```

### Issue: Port 5173 already in use (Vite)

**Solution:** Vite will automatically use the next available port, or specify:
```bash
npm run dev -- --port 3000
```

### Issue: CORS errors in browser console

**Solution:** Make sure the API is running on port 8000 and the UI is connecting to it. Check `apps/shail-ui/vite.config.js` for proxy settings.

### Issue: Tasks stuck in "queued" status

**Solution:** 
1. Check Terminal 2 (Worker) - is it running and showing "[Worker] Processing task..."?
2. Check Terminal 1 (Redis) - is it running?
3. Check Redis connection: `redis-cli ping` should return `PONG`

### Issue: Worker crashes with `KeyError: 'gemini_api_key'`

**Solution:** The worker needs the `GEMINI_API_KEY` environment variable set. 

**Fix:**
1. Stop the worker (Ctrl+C)
2. Set the environment variable:
   ```bash
   export GEMINI_API_KEY="your_api_key_here"
   ```
3. Restart the worker:
   ```bash
   python -m shail.workers.task_worker
   ```

**Note:** The environment variable must be set in the same terminal session where you run the worker. If you open a new terminal, you'll need to set it again, or add it to your shell profile (`~/.zshrc` or `~/.bashrc`).

---

## Architecture Overview

```
User Browser (Port 5173)
    ↓ HTTP/WebSocket
FastAPI Server (Port 8000)
    ↓ HTTP requests
ShailCoreRouter → MasterPlanner → Agent Selection
    ↓ Task execution
Redis Queue (Port 6379)
    ↓ Task pickup
Worker Process
    ↓ Execute agent
Agent Tools (CodeAgent, etc.)
```

---

## Next Steps

Once everything is running:

1. **Explore the UI** - Try different commands and watch the system route them intelligently
2. **Test Safety** - Try dangerous commands and see the permission flow
3. **Check API Docs** - Visit http://localhost:8000/docs for full API documentation
4. **View Logs** - Watch Terminal 2 (Worker) for detailed execution logs

---

## Stopping Services

To stop all services:

1. In each terminal, press `Ctrl+C`
2. Stop Redis: `redis-cli shutdown` (or `Ctrl+C` in Terminal 1)

---

**Enjoy testing Shail! 🚀**

