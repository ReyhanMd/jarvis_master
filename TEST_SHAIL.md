# 🧪 Test Shail - Verify the "One Statement" Fix

## ✅ All Services Are Running

- **Redis**: Port 6379
- **Worker**: PID 4799 (processing tasks in background)
- **API**: http://localhost:8000 
- **UI**: http://localhost:3000

## 🎯 How to Test

### Step 1: Open the UI
```
Open your browser to: http://localhost:3000
```

You should see the Shail dashboard with:
- Chat input on the left
- Task Queue on the right
- Conversation panel below

### Step 2: Submit a Test Command

**Type this in the chat input:**
```
list files in the current directory
```

**Press Send** and watch what happens.

### Step 3: What You Should See

✅ **SUCCESS** - If you see:
- A "pending" or "running" status in the Conversation panel
- The task appears in the Task Queue
- After a few seconds, you get a **file list** as the response
- **NO error message** saying "You can only execute one statement at a time"

❌ **STILL BROKEN** - If you see:
- The old error message: "Error: You can only execute one statement at a time"
- Status shows "failed"

### Step 4: Test a Multi-Step Command

If the first test worked, try something more complex:
```
create a new directory called test_folder
```

This should work without any "one statement" error.

### Step 5: Test Desktop Control (FriendAgent)

Try:
```
hey friend, what's the current mouse position?
```

This will route to the FriendAgent and should work.

## 📊 Check Logs (If Something Fails)

```bash
# Worker logs
tail -f /Users/reyhan/shail_master/worker.log

# API logs  
tail -f /Users/reyhan/shail_master/api.log

# UI logs
tail -f /Users/reyhan/shail_master/ui.log
```

## 🔥 Stop All Services

When you're done testing:
```bash
cd /Users/reyhan/shail_master
kill 4799 4840 4871
redis-cli shutdown
```

## 🚀 Restart Everything

To restart all services fresh:
```bash
cd /Users/reyhan/shail_master
./RESTART_ALL.sh
```

---

**The Fix:** Both `CodeAgent` and `FriendAgent` now have explicit prompts that tell Gemini:
- ✅ You CAN execute multiple tools sequentially
- ✅ Multi-step operations are expected and encouraged
- ❌ NEVER say "You can only execute one statement at a time"

The error should be GONE. If it persists, check the worker logs to see if there's a startup error.

