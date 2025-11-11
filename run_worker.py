#!/usr/bin/env python3 -u
"""
Direct runner for Shail Task Worker.
This script sets up the Python path correctly before importing the worker.
Note: -u flag enables unbuffered output (critical for background processes)
"""

import sys
import os

# Force unbuffered output for logging
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[DEBUG] Starting run_worker.py...")
print(f"[DEBUG] Python version: {sys.version}")
print(f"[DEBUG] Python executable: {sys.executable}")

# Get the project root (this file is at project root)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
print(f"[DEBUG] Project root: {PROJECT_ROOT}")

# Add project root to Python path FIRST
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    print(f"[DEBUG] Added {PROJECT_ROOT} to sys.path")

# Verify shail package exists
shail_path = os.path.join(PROJECT_ROOT, "shail", "__init__.py")
print(f"[DEBUG] Looking for shail at: {shail_path}")
print(f"[DEBUG] Shail exists: {os.path.exists(shail_path)}")

if not os.path.exists(shail_path):
    print(f"ERROR: Cannot find shail package at {shail_path}")
    print(f"Project root: {PROJECT_ROOT}")
    sys.exit(1)

# Manually load shail module (works around macOS case-insensitivity issues)
import importlib.util
try:
    print("[DEBUG] Loading shail module...")
    # Load shail module directly
    spec = importlib.util.spec_from_file_location("shail", shail_path)
    if spec and spec.loader:
        shail_module = importlib.util.module_from_spec(spec)
        sys.modules["shail"] = shail_module
        spec.loader.exec_module(shail_module)
        print("✓ Loaded shail module")
    else:
        raise ImportError("Could not create spec for shail module")
except Exception as e:
    print(f"ERROR: Failed to load shail module: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Now import and run the worker
try:
    print("[DEBUG] Importing worker module...")
    from shail.workers.task_worker import main
    print("[DEBUG] Worker module imported successfully")
    print("[DEBUG] Starting worker main()...")
    main()
except ImportError as e:
    print(f"ERROR: Failed to import worker: {e}")
    print(f"Python path: {sys.path[:3]}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except KeyboardInterrupt:
    print("\nWorker stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"ERROR: Unexpected error in worker: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

