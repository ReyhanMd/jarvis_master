# 🚀 How to Use Shail - Simple Guide

## Quick Start (3 Steps)

### 1. Start Everything
```bash
cd /Users/reyhan/shail_master
./RESTART_ALL.sh
```

You'll see:
```
✅ ALL SERVICES STARTED SUCCESSFULLY

📊 Redis:       Running on port 6379
🧠 Worker:      Running
🌐 API:         Running on http://localhost:8000
🎨 UI:          Running on http://localhost:3000
```

### 2. Open the UI
```bash
open http://localhost:3000
```

### 3. Chat with Shail!

Type commands like:
- "list files in the current directory"
- "create a directory called my_folder"  
- "open Calculator"
- "move my mouse to position 500, 500" (will ask permission)

That's it! 🎉

---

## Stop Everything
```bash
# Use the kill command shown by RESTART_ALL.sh, or:
cd /Users/reyhan/shail_master
pkill -f "run_worker|uvicorn|vite"
redis-cli shutdown
```

---

## Troubleshooting

**If services don't start:**
```bash
# Check if ports are in use
lsof -i :6379  # Redis
lsof -i :8000  # API
lsof -i :3000  # UI

# Kill and restart
./RESTART_ALL.sh
```

**Check logs:**
```bash
tail -f worker.log  # Worker activity
tail -f api.log     # API requests
tail -f ui.log      # UI errors
```

---

## What Shail Can Do

### File Operations
- "list files"
- "create a file called test.txt"
- "read the file README.md"
- "delete the file test.txt"

### Desktop Control (asks permission)
- "move my mouse to 500, 500"
- "click the mouse"
- "type hello world"
- "press the enter key"
- "open Safari"
- "focus the Terminal window"

### Coding (CodeAgent)
- "create a Python script that prints hello world"
- "run the command ls -la"
- "build a simple web page"

### Conversation (FriendAgent)
- "hey friend, help me click something"
- "what's my screen size?"
- "list all open windows"

---

## 🎯 Key Features

- **Intelligent Routing:** Master Planner chooses the right agent
- **Safety First:** Dangerous operations require your approval
- **Async Execution:** Tasks run in background, UI stays responsive
- **Real-time Updates:** See task progress live
- **Multi-step Operations:** Agent can execute complex workflows

---

**Enjoy using Shail!** 🚀

