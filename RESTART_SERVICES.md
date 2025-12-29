# Restart Shail Services

## The prompts have been fixed! Now restart to load the changes:

### Terminal 2 (Worker)
1. Press `Ctrl+C` to stop the worker
2. Run: `./start_worker.sh`

You should see:
```
[Worker] Starting task worker (polling queue 'shail_tasks')...
[Worker] Poll timeout: 5s
```

### Terminal 3 (API)
The API with `--reload` should auto-restart when it detects file changes.

If it doesn't, manually restart:
1. Press `Ctrl+C`
2. Run: `uvicorn apps.shail.main:app --reload`

You should see:
```
INFO:     Application startup complete.
```

---

## Then test with these commands:

### Test 1: List files (uses tools)
```
list files in the current directory
```

### Test 2: Desktop control (requires permission)
```
move my mouse to position 500, 500
```

### Test 3: Multi-step operation
```
create a file called test.txt and write hello world to it
```

---

## What to look for:

- ✅ No "one statement at a time" error
- ✅ Commands execute successfully
- ✅ Permission modals appear for dangerous operations
- ✅ Chat shows real responses instead of errors

The error should be gone after restart!

