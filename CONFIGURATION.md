# Shail Configuration Guide

Shail uses environment variables for configuration. You can set these in two ways:

## Method 1: .env File (Recommended)

The easiest and most user-friendly way to configure Shail is using a `.env` file.

### Setup

1. **Copy the example file:**
   ```bash
   cd /Users/reyhan/jarvis_master
   cp .env.example .env
   ```

2. **Edit `.env` and add your API key:**
   ```bash
   # Open .env in your editor
   nano .env  # or use your preferred editor
   
   # Change this line:
   GEMINI_API_KEY=your_gemini_api_key_here
   
   # To:
   GEMINI_API_KEY=AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI
   ```

3. **Save the file**

4. **That's it!** Shail will automatically load the `.env` file when it starts.

### Benefits

- ✅ **One-time setup** - Create the file once, works forever
- ✅ **No terminal exports** - Works regardless of how you start Shail
- ✅ **Production-ready** - Works in packaged apps
- ✅ **Secure** - `.env` file is gitignored (won't be committed)

---

## Method 2: Terminal Export (Alternative)

If you prefer to export environment variables in your terminal:

```bash
export GEMINI_API_KEY="AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI"
```

**Note:** This only works for that terminal session. You'll need to export again in each new terminal.

---

## Configuration Variables

### Required

- **`GEMINI_API_KEY`** - Your Google Gemini API key
  - Get it from: https://aistudio.google.com/app/apikey
  - Required for: Master Planner, CodeAgent, and all LLM features

### Optional

- **`GEMINI_MODEL`** - Model to use (default: `gemini-2.0-flash`)
  - Options: `gemini-2.0-flash`, `gemini-pro`, `gemini-1.5-pro`

- **`REDIS_URL`** - Redis connection (default: `redis://localhost:6379/0`)

- **`SHAIL_SQLITE`** - Database path (default: `./shail_memory.sqlite3`)

- **`SHAIL_AUDIT_LOG`** - Audit log path (default: `./shail_audit.jsonl`)

- **`SHAIL_WORKSPACE_ROOT`** - Workspace directory (default: current directory)

- **`SHAIL_TASK_QUEUE`** - Queue name (default: `shail_tasks`)

---

## Priority Order

If you set the same variable in multiple places, Shail uses this priority:

1. **Environment variable** (terminal export) - Highest priority
2. **.env file** - Used if env var not set
3. **Default value** - Used if neither is set

This allows you to override `.env` settings for testing.

---

## Security

- ✅ `.env` file is automatically gitignored
- ✅ Never commit your `.env` file to version control
- ✅ The `.env.example` file is a template (no real keys)

---

## Troubleshooting

### Worker can't find API key

**Check:**
1. Does `.env` file exist in project root?
2. Is `GEMINI_API_KEY` set in `.env`?
3. Is the variable name correct? (Must be uppercase: `GEMINI_API_KEY`)

**Solution:**
```bash
# Verify .env file exists and has the key
cat .env | grep GEMINI_API_KEY

# Should show:
# GEMINI_API_KEY=your_actual_key_here
```

### Settings not loading

**Check:**
1. Is `python-dotenv` installed? `pip list | grep python-dotenv`
2. Is `.env` file in the project root? (same directory as `start_worker.sh`)

---

## For Developers

The `.env` file is loaded automatically by `apps/shail/settings.py`:

```python
from dotenv import load_dotenv
load_dotenv()  # Loads .env from project root
```

All settings then use `os.getenv()` which reads from:
1. Environment variables (if set)
2. `.env` file (if exists)
3. Default values (if neither)

