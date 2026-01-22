# 🚀 Shail System - Next Steps & Execution Plan

## ✅ Current Status

### What's Working:
1. **✅ CaptureService** - Screen recording is LIVE!
   - WebSocket: `ws://localhost:8765/capture`
   - Health Check: `http://localhost:8767/health`
   - Streaming at 30 FPS with JPEG compression
   - Permission granted and working

### What's Next:

---

## 📋 Step-by-Step Execution Plan

### **STEP 1: Start AccessibilityBridge** (5 minutes)

**Why:** AccessibilityBridge provides real-time UI element tracking (buttons, text fields, windows). This is essential for the UI Twin service to understand what's on screen.

**How:**

1. **Open AccessibilityBridge in Xcode:**
   ```bash
   open /Users/reyhan/shail_master/native/mac/AccessibilityBridge/AccessibilityBridge.xcodeproj
   ```

2. **Build and Run:**
   - Press `⌘+B` to build
   - Press `⌘+R` to run
   - **Grant Accessibility permission** when prompted

3. **Verify it's working:**
   - You should see: `AccessibilityBridge LIVE at ws://localhost:8766/accessibility`
   - Health check: `http://localhost:8768/health`

**Expected Console Output:**
```
♿ AccessibilityBridge initializing...
✅ Accessibility permission GRANTED!
🌐 Starting WebSocket server on port 8766...
🏥 Starting health check server on port 8768...
🟢 AccessibilityBridge LIVE at ws://localhost:8766/accessibility
```

---

### **STEP 2: Start Python Services** (10 minutes)

**Why:** These services process the screen data, execute actions, and orchestrate tasks.

**Option A: Use the All-in-One Script (Easiest)**
```bash
cd /Users/reyhan/shail_master
./START_ALL.sh
```

**Option B: Manual Start (More Control)**

Open **5 separate terminal windows**:

#### Terminal 1: UI Twin Service
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate  # or create: python3 -m venv services_env
cd services/ui_twin
python service.py
```
**Expected:** Connects to CaptureService and AccessibilityBridge WebSockets

#### Terminal 2: Action Executor
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd services/action_executor
python service.py
```
**Expected:** `✅ Action Executor running on http://localhost:8080`

#### Terminal 3: Vision Service
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd services/vision
python service.py
```
**Expected:** `✅ Vision service running on http://localhost:8081`

#### Terminal 4: RAG Retriever
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
cd services/rag_retriever
python service.py
```
**Expected:** `✅ RAG Retriever running on http://localhost:8082`

#### Terminal 5: Planner Service
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
export GEMINI_API_KEY="your-key-here"  # Required!
cd services/planner
python service.py
```
**Expected:** `✅ Planner service running on http://localhost:8083`

---

### **STEP 3: Start Shail Core Services** (5 minutes)

**Why:** These are the main orchestration layer that coordinates everything.

#### Terminal 6: Redis (Task Queue)
```bash
redis-server
```
**Expected:** Redis starts on port 6379

#### Terminal 7: Shail Worker
```bash
cd /Users/reyhan/shail_master
export GEMINI_API_KEY="your-key-here"  # Required!
python -m shail.workers.task_worker
```
**Expected:** `[Worker] Starting task worker (polling queue 'shail_tasks')...`

#### Terminal 8: Shail API
```bash
cd /Users/reyhan/shail_master
uvicorn apps.shail.main:app --reload
```
**Expected:** `INFO: Uvicorn running on http://127.0.0.1:8000`

#### Terminal 9: Shail UI (Optional - Web Dashboard)
```bash
cd /Users/reyhan/shail_master/apps/shail-ui
npm install  # First time only
npm run dev
```
**Expected:** `Local: http://localhost:5173/`

---

## 🧪 Testing the Integration

### Test 1: Verify Native Services
```bash
cd /Users/reyhan/shail_master
./check_native_health.sh
```

**Expected Output:**
```
✅ CaptureService: Running, WebSocket listening, Health check OK
✅ AccessibilityBridge: Running, WebSocket listening, Health check OK
```

### Test 2: Verify Python Services
```bash
curl http://localhost:8080/health  # Action Executor
curl http://localhost:8081/health  # Vision
curl http://localhost:8082/health  # RAG Retriever
curl http://localhost:8083/health  # Planner
```

**Expected:** All return `{"status": "ok"}`

### Test 3: Test Screen Capture Connection
```python
import asyncio
import websockets

async def test_capture():
    uri = "ws://localhost:8765/capture"
    async with websockets.connect(uri) as ws:
        print("✅ Connected to CaptureService!")
        # Receive a frame
        frame = await ws.recv()
        print(f"📸 Received frame: {len(frame)} bytes")

asyncio.run(test_capture())
```

### Test 4: Test Accessibility Events
```python
import asyncio
import websockets

async def test_accessibility():
    uri = "ws://localhost:8766/accessibility"
    async with websockets.connect(uri) as ws:
        print("✅ Connected to AccessibilityBridge!")
        # Receive an event
        event = await ws.recv()
        print(f"♿ Received event: {event}")

asyncio.run(test_accessibility())
```

### Test 5: Test Full Task Execution
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Take a screenshot of the current screen"
  }'
```

---

## 📊 Service Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│  (Browser UI at http://localhost:5173)                  │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP
                     ↓
┌─────────────────────────────────────────────────────────┐
│              Shail API (FastAPI)                        │
│              http://localhost:8000                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│            Master Planner Service                       │
│            http://localhost:8083                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Vision     │  │   RAG        │  │   Action     │  │
│  │   :8081      │  │   :8082      │  │   :8080      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              Redis Queue (Task Queue)                    │
│              localhost:6379                              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              Task Worker                                │
│              (Executes tasks from queue)                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              UI Twin Service                             │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │  CaptureService │  │ Accessibility    │            │
│  │  ws://:8765     │  │ Bridge          │            │
│  │  (Screen Frames) │  │ ws://:8766      │            │
│  │                  │  │ (UI Events)     │            │
│  └──────────────────┘  └──────────────────┘            │
└─────────────────────────────────────────────────────────┘
```

---

## 🎯 What Each Service Does

### Native Services (Swift)
- **CaptureService**: Streams screen frames at 30 FPS via WebSocket
- **AccessibilityBridge**: Streams UI element events (clicks, focus, windows) via WebSocket

### Python Services
- **UI Twin**: Consumes screen frames and accessibility events, maintains real-time UI state
- **Vision**: OCR and visual understanding of screenshots
- **Action Executor**: Executes mouse/keyboard actions and window management
- **RAG Retriever**: Semantic search over past tasks and documentation
- **Planner**: Orchestrates tasks using LLM (Gemini)

### Core Services
- **Shail API**: Main HTTP API for the UI
- **Task Worker**: Picks up tasks from Redis queue and executes them
- **Redis**: Task queue for async task processing

---

## 🔥 Quick Start Commands

### Start Everything (Recommended)
```bash
cd /Users/reyhan/shail_master

# 1. Start native services (if not already running in Xcode)
./run_native_services.sh

# 2. Start all Python services
./START_ALL.sh

# 3. Start Shail core
redis-server &  # In separate terminal
export GEMINI_API_KEY="your-key"
python -m shail.workers.task_worker &  # In separate terminal
uvicorn apps.shail.main:app --reload &  # In separate terminal
```

### Check Everything
```bash
./check_native_health.sh  # Native services
curl http://localhost:8080/health  # Python services
redis-cli ping  # Redis
```

---

## 🐛 Troubleshooting

### Issue: AccessibilityBridge permission denied
**Solution:** 
1. System Settings → Privacy & Security → Accessibility
2. Add AccessibilityBridge.app manually if not listed
3. Toggle ON
4. Restart the app

### Issue: Python services can't connect to native services
**Solution:**
1. Verify native services are running: `./check_native_health.sh`
2. Check ports: `lsof -i :8765` and `lsof -i :8766`
3. Restart native services if needed

### Issue: "Module not found" errors
**Solution:**
```bash
cd /Users/reyhan/shail_master
source services_env/bin/activate
pip install -r requirements.txt
```

### Issue: GEMINI_API_KEY not found
**Solution:**
```bash
export GEMINI_API_KEY="your-key-here"
# Or create .env file with GEMINI_API_KEY=your-key-here
```

---

## 🎉 Success Criteria

You'll know everything is working when:

1. ✅ CaptureService console shows: `Streaming at 30 FPS`
2. ✅ AccessibilityBridge console shows: `AccessibilityBridge LIVE`
3. ✅ All Python services return `{"status": "ok"}` on health checks
4. ✅ UI Twin service logs show: `Connected to CaptureService` and `Connected to AccessibilityBridge`
5. ✅ You can send a task via API and see it execute

---

## 📝 Next: Test Real Tasks

Once everything is running, try:

1. **Simple task:** "Take a screenshot"
2. **UI interaction:** "Click the Safari icon in the dock"
3. **Complex task:** "Open Safari, go to google.com, and search for 'Shail AI'"

Watch the logs to see how the system:
- Captures the screen
- Analyzes UI elements
- Plans the action
- Executes it
- Verifies the result

---

**You're almost there! 🚀**

