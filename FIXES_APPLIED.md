# Fixes Applied - Service Import Issues

## Problem
Python services were failing to start because of relative import errors when run directly as scripts.

## Solution
Updated all service files to handle both:
1. **Running as modules** (relative imports: `.models`)
2. **Running directly** (absolute imports: `action_executor.models`)

## Files Fixed

### 1. `services/action_executor/service.py`
- Fixed imports for `Action`, `ActionResult`, etc.
- Fixed imports for `ElementSelector` from `ui_twin`
- Fixed imports for platform executors (`macos`, `windows`)

### 2. `services/ui_twin/service.py`
- Fixed imports for `UIElement`, `UISnapshot`, `ElementSelector`

### 3. `services/vision/service.py`
- Fixed imports for `VisionResult`, `OCRResult`, etc.

### 4. `services/rag_retriever/service.py`
- Fixed imports for `Document`, `Query`, `RetrievalResult`

### 5. `services/planner/service.py`
- Fixed imports for `Task`, `Plan`, `PlanStep`, etc.
- Fixed imports for `create_planner_graph`

### 6. Startup Scripts
- Added pip upgrade step to fix old pip version warnings
- Both `START_PYTHON_SERVICES.sh` and `START_NATIVE_SERVICES.sh` updated

## How It Works Now

Each service uses a try/except pattern:

```python
try:
    from .models import SomeModel  # Works when run as module
except ImportError:
    # Works when run directly as script
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from service_name.models import SomeModel
```

## Next Steps

### Option 1: Test Python Services (No Xcode Needed)
```bash
./START_PYTHON_SERVICES.sh
```

Then test:
```bash
./test_services.sh
```

### Option 2: Install Xcode for Full System
1. Install Xcode from App Store
2. Run: `sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer`
3. Run: `sudo xcodebuild -license accept`
4. Run: `./START_NATIVE_SERVICES.sh`

See `INSTALL_XCODE.md` for detailed instructions.

## What Should Work Now

✅ All Python services start without import errors
✅ Services can be run directly with `python service.py`
✅ Services can be run as modules
✅ Pip is upgraded automatically
✅ All dependencies install correctly

## Testing

After starting services, verify they're running:

```bash
curl http://localhost:8080/health  # Action Executor
curl http://localhost:8081/health  # Vision
curl http://localhost:8082/health  # RAG Retriever
curl http://localhost:8083/health  # Planner
```

All should return `{"status": "ok", ...}`
