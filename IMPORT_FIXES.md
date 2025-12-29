# Import Fixes Applied

## Problem
Services were crashing with `ImportError: attempted relative import with no known parent package` when run directly as scripts.

## Root Cause
Python's relative imports (`.models`) only work when the module is part of a package. When running `python service.py` directly, Python doesn't know about the package structure.

## Solution
Updated all service files to:
1. **Add parent directory to sys.path** for direct script execution
2. **Try relative imports first** (when run as module)
3. **Fallback to absolute imports** (when run as script)
4. **Use direct file imports** as last resort (for executors)

## Files Fixed

### All Services
- `services/action_executor/service.py`
- `services/ui_twin/service.py`
- `services/vision/service.py`
- `services/rag_retriever/service.py`
- `services/planner/service.py`

### Pattern Used
```python
# Add parent directory to path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative, fallback to absolute
try:
    from .models import SomeModel
except (ImportError, ValueError):
    from service_name.models import SomeModel
```

## Testing

Now you can run:
```bash
./START_PYTHON_SERVICES.sh
```

Services should start without import errors!

## Next Steps

1. **Test the services**: Run `./START_PYTHON_SERVICES.sh`
2. **Check logs**: `tail -f logs/action_executor.log`
3. **Test endpoints**: `curl http://localhost:8080/health`
4. **Install Xcode**: For native services (see `INSTALL_XCODE.md`)

