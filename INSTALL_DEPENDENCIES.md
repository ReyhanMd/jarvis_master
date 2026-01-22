# Installing Shail Dependencies

## The Problem

You're getting `ModuleNotFoundError: No module named 'redis'` because the required Python packages aren't installed in your virtual environment.

## The Solution

Install all dependencies in your `jarvis-env` virtual environment:

```bash
cd /Users/reyhan/shail_master

# Activate your virtual environment
source jarvis-env/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

Or install individually:

```bash
source jarvis-env/bin/activate

pip install fastapi uvicorn pydantic python-dotenv
pip install langchain langchain-google-genai langchain-core
pip install redis
pip install requests
```

## Verify Installation

After installing, verify:

```bash
source jarvis-env/bin/activate
python -c "import redis; import fastapi; import langchain; print('✅ All packages installed!')"
```

## Then Try Worker Again

```bash
./start_worker.sh
```

Or:

```bash
source jarvis-env/bin/activate
python run_worker.py
```

---

## Quick Install Command

Copy and paste this entire block:

```bash
cd /Users/reyhan/shail_master
source jarvis-env/bin/activate
pip install fastapi uvicorn pydantic python-dotenv langchain langchain-google-genai langchain-core redis requests
```

This will install all required packages.

