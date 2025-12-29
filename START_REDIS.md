# Starting Redis Server

## The Issue

Your Shail worker is trying to connect to Redis, but Redis server is not running.

## Quick Fix

**Start Redis in a separate terminal:**

```bash
redis-server
```

You should see output like:
```
* Ready to accept connections
```

## Install Redis (if not installed)

If you get `command not found: redis-server`, install Redis:

**macOS (using Homebrew):**
```bash
brew install redis
brew services start redis
```

Or start it manually:
```bash
brew install redis
redis-server
```

## Verify Redis is Running

Test the connection:
```bash
redis-cli ping
```

You should see: `PONG`

## Full Startup Sequence

For Shail to work, you need **4 terminals**:

1. **Terminal 1: Redis** (Message Bus)
   ```bash
   redis-server
   ```

2. **Terminal 2: Shail Worker** (The Brain)
   ```bash
   cd /Users/reyhan/jarvis_master
   source jarvis-env/bin/activate
   ./start_worker.sh
   ```

3. **Terminal 3: Shail API** (The Front Door)
   ```bash
   cd /Users/reyhan/jarvis_master
   source jarvis-env/bin/activate
   uvicorn apps.shail.main:app --reload
   ```

4. **Terminal 4: Shail UI** (The Cockpit)
   ```bash
   cd /Users/reyhan/jarvis_master/apps/shail-ui
   npm run dev
   ```

Once Redis is running, the worker will stop showing errors and start polling for tasks!

