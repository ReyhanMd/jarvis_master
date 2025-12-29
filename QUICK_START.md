# 🚀 Quick Start Guide - Fix the Redis Error

## The Problem

Your worker is showing this error:
```
Failed to connect to Redis at redis://localhost:6379/0. Connection refused.
```

This means **Redis server is not running**. Redis is the "message bus" that Shail uses to queue tasks.

## The Solution

### Step 1: Install Redis (if not installed)

**Check if Redis is installed:**
```bash
which redis-server
```

If it says "not found", install it:

**macOS:**
```bash
brew install redis
```

**If you don't have Homebrew:**
```bash
# Install Homebrew first
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install Redis
brew install redis
```

### Step 2: Start Redis Server

**Open a NEW terminal window** (keep your worker terminal running) and run:

```bash
redis-server
```

You should see:
```
* Ready to accept connections
```

**Leave this terminal running!** Redis needs to stay running in the background.

### Step 3: Verify Redis is Working

In yet another terminal, test Redis:

```bash
redis-cli ping
```

You should see: `PONG`

### Step 4: Your Worker Should Now Work!

Go back to your worker terminal. The errors should stop, and you should see:

```
[Worker] No task in queue, sleeping for 5s...
```

This means the worker is successfully connected to Redis and waiting for tasks!

---

## Complete Startup Sequence

For the full Shail system, you need **4 terminal windows**:

### Terminal 1: Redis (Message Bus)
```bash
redis-server
```

### Terminal 2: Shail Worker (The Brain)
```bash
cd /Users/reyhan/jarvis_master
source jarvis-env/bin/activate
./start_worker.sh
```

### Terminal 3: Shail API (The Front Door)
```bash
cd /Users/reyhan/jarvis_master
source jarvis-env/bin/activate
uvicorn apps.shail.main:app --reload
```

### Terminal 4: Shail UI (The Cockpit)
```bash
cd /Users/reyhan/jarvis_master/apps/shail-ui
npm run dev
```

---

## Quick Install Command

If you just want to install Redis quickly:

```bash
# Install Redis
brew install redis

# Start Redis (in a new terminal)
redis-server
```

That's it! Your worker will connect automatically once Redis is running.

