# WebSocket Debug Summary

## Issues Found

1. **Multiple Backend Instances**: There are 3 Python processes listening on port 8000
   - PID 10673: Using Python 3.13 from homebrew
   - PID 14808: Another instance
   - PID 18049: Using jarvis-env (different virtual environment)

2. **WebSocket Connection Failing**: Swift UI gets "bad response from server" error
   - Swift UI logs show connection attempt
   - No backend logs showing WebSocket acceptance
   - This suggests the WebSocket handshake is failing

## Fixes Applied

1. **Added Comprehensive Logging**:
   - Added logs at WebSocket route entry point (`main.py:websocket_brain`)
   - Added logs in WebSocket endpoint handler (`websocket_server.py:websocket_endpoint`)
   - Added error handling with detailed logging

2. **Enhanced Error Handling**:
   - Wrapped WebSocket endpoint in try-except
   - Added logging for all error paths
   - Added exception info logging

## Next Steps

1. **Kill Duplicate Backend Instances**:
   ```bash
   # Find and kill old processes
   kill 10673 14808  # Keep only the one in services_env
   ```

2. **Restart Backend** (Terminal 1):
   ```bash
   cd /Users/reyhan/shail_master
   source services_env/bin/activate
   cd apps/shail
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Test WebSocket Connection**:
   - Start Swift UI
   - Press Option+S
   - Check logs for WebSocket connection messages

## Expected Log Flow

When WebSocket connects successfully, you should see:
1. `main.py:websocket_brain: WebSocket route called`
2. `websocket_server.py:websocket_endpoint: WebSocket endpoint called`
3. `websocket_server.py:connect: WebSocket client connected`
4. `websocket_server.py:websocket_endpoint: WebSocket accepted, entering message loop`

If connection fails, you'll see error logs at the point of failure.
