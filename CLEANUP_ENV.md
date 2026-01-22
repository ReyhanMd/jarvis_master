# .env File Cleanup Guide

## The Problem

You have multiple `.env` files in your project:
- `./.env` (project root) ✅ **CORRECT - This is the one we want**
- `./SHAIL/.env` ❌ **OLD - This should be removed**
- `./Reyhan-scooby-DOO/.env` (old project)
- `./sachdevaAI_code/.env` (old project)

## The Solution

Shail looks for `.env` file in the **project root** (`/Users/reyhan/shail_master/.env`).

### Step 1: Verify Your Root .env File

Check that your root `.env` file has your API key:

```bash
cd /Users/reyhan/shail_master
cat .env | grep GEMINI_API_KEY
```

Should show:
```
GEMINI_API_KEY=AIzaSyC0d1jFHVGBjLSrdq_8VhX8OtTH3uj4yOI
```

### Step 2: Remove Old .env Files (Optional)

If you want to clean up the old `.env` files:

```bash
cd /Users/reyhan/shail_master

# Remove old SHAIL/.env (if it exists)
rm SHAIL/.env 2>/dev/null || echo "Already removed"

# The .env files in other directories (Reyhan-scooby-DOO, sachdevaAI_code) 
# are from old projects and can be left alone or removed
```

### Step 3: Verify Settings Loading

The `apps/shail/settings.py` file now correctly looks for `.env` at:
- `/Users/reyhan/shail_master/.env` ✅

It will NOT look in:
- `SHAIL/.env` ❌
- `SHAIL/workers/.env` ❌

## How It Works

The path calculation in `settings.py`:
- File location: `apps/shail/settings.py`
- Goes up 3 levels: `apps` → (project root)
- Looks for: `(project root)/.env`

## Verification

To test that the correct .env is being loaded:

```bash
cd /Users/reyhan/shail_master
python3 -c "
from apps.shail.settings import get_settings
settings = get_settings()
if settings.gemini_api_key:
    print('✓ API key loaded successfully!')
    print(f'Key starts with: {settings.gemini_api_key[:10]}...')
else:
    print('✗ API key not found')
"
```

This should show your API key is loaded.

