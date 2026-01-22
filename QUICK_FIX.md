# 🔧 Quick Fix: Worker Crash Issue

## The Problem

If your worker (Terminal 2) is crashing with:
```
KeyError: 'gemini_api_key'
```

This means the `GEMINI_API_KEY` environment variable is not set.

## The Solution

**Method 1: Create .env File (Recommended - Easiest)**

This is the best long-term solution. Create a `.env` file once and you're done:

```bash
cd /Users/reyhan/shail_master

# Copy the example file
cp .env.example .env

# Edit .env and add your API key:
# GEMINI_API_KEY=AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI

# Now start the worker (it will automatically load .env)
python -m shail.workers.task_worker
```

**OR use the helper script:**
```bash
cd /Users/reyhan/shail_master
./start_worker.sh
```

**Method 2: Terminal Export (Quick Fix)**

If you need a quick fix without creating .env file:

```bash
cd /Users/reyhan/shail_master

# Set your Gemini API key (NOTE: Must be UPPERCASE: GEMINI_API_KEY)
# The code looks for GEMINI_API_KEY, NOT gemini_api_key (lowercase)
export GEMINI_API_KEY="AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI"

# Optional: Set PYTHONPATH to ensure imports work
export PYTHONPATH="$PWD:$PYTHONPATH"

# Now run the worker
python -m shail.workers.task_worker
```

**Important:** 
- The environment variable must be `GEMINI_API_KEY` (all uppercase), not `gemini_api_key` (lowercase)
- The settings.py file uses `os.getenv("GEMINI_API_KEY")` which is case-sensitive
- **Preferred:** Use Method 1 (.env file) - it's easier and works better for packaged apps

**That's it!** The worker should now start successfully.

## Why This Happens

The worker needs the Gemini API key because:
1. It loads the **Master Planner** (Priority 3) which uses Gemini to route tasks intelligently
2. It loads the **CodeAgent** which uses Gemini for code generation
3. Without the key, these components fail to initialize

## Making It Permanent (Optional)

If you want to avoid setting this every time, add it to your shell profile:

```bash
# Add to ~/.zshrc (if using zsh) or ~/.bashrc (if using bash)
echo 'export GEMINI_API_KEY="AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI"' >> ~/.zshrc

# Reload your shell
source ~/.zshrc
```

## Verify It's Working

After setting the key and starting the worker, you should see:
```
[Worker] Starting task worker (polling queue 'shail_tasks')...
[Worker] Poll timeout: 5s
```

No more `KeyError`! 🎉

