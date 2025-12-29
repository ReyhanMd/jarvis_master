# Phase 3: Accessibility Control - Implementation Complete

## Overview
Phase 3 implements control functions (click, type, window info) in AccessibilityBridge and integrates them with Action Executor and UI Twin services.

## Completed Components

### 1. AXController (Native macOS)
**File**: `native/mac/AccessibilityBridge/AXController.swift`

- ✅ `click(x: Int, y: Int)` - Mouse click using CGEvent
- ✅ `typeText(text: String)` - Keyboard input using CGEvent
- ✅ `pressKey(key: String)` - Key press using CGEvent
- ✅ `getActiveWindowInfo()` - Returns active window/app information
- ✅ `getElementAt(x: Int, y: Int)` - Returns AXUIElement at coordinates

**Key Features:**
- Uses CGEvent for reliable input simulation
- Proper key code mapping for common keys
- Window and element information extraction
- Error handling and validation

### 2. WebSocket Command Handlers
**File**: `native/mac/AccessibilityBridge/AXWebSocketServer.swift` (MODIFIED)

- ✅ Handles incoming control commands via WebSocket
- ✅ Commands: `click`, `type`, `press_key`, `get_active_window`, `get_element_at`
- ✅ JSON request/response protocol
- ✅ Error handling and validation

**Command Protocol:**
```json
// Request
{
  "command": "click",
  "x": 100,
  "y": 200
}

// Response
{
  "type": "command_response",
  "command": "click",
  "success": true,
  "x": 100,
  "y": 200
}
```

### 3. Action Executor Integration
**File**: `services/action_executor/executors/macos.py` (MODIFIED)

- ✅ Connects to AccessibilityBridge WebSocket (port 8766)
- ✅ Sends control commands via WebSocket
- ✅ Falls back to PyAutoGUI if AccessibilityBridge unavailable
- ✅ Supports click, type, and press_key actions

**Key Features:**
- Prefers AccessibilityBridge (native, more reliable)
- Automatic fallback to PyAutoGUI
- Proper error handling and logging
- Timeout handling for WebSocket operations

### 4. UI Twin executeAction Method
**File**: `services/ui_twin/service.py` (MODIFIED)

- ✅ `executeAction(selector, action, action_executor_url)` method
- ✅ Translates element selectors to coordinates
- ✅ Routes to Action Executor service
- ✅ Returns action results

**Usage:**
```python
selector = ElementSelector(role="AXButton", text="Submit")
result = await ui_twin.executeAction(selector, "click")
```

## Architecture Flow

```
Action Executor          AccessibilityBridge          macOS System
     |                            |                        |
     |-- WebSocket command -->   |                        |
     |                            |-- CGEvent click -->    |
     |                            |                        |-- UI Action
     |<-- Response -------------- |                        |
```

## Files Created/Modified

### New Files:
1. `native/mac/AccessibilityBridge/AXController.swift`

### Modified Files:
1. `native/mac/AccessibilityBridge/AXWebSocketServer.swift` - Added command handlers
2. `services/action_executor/executors/macos.py` - Added AccessibilityBridge integration
3. `services/action_executor/requirements.txt` - Added websockets dependency
4. `services/ui_twin/service.py` - Added executeAction method
5. `services/ui_twin/requirements.txt` - Added httpx dependency

## Command Reference

### Click Command
```json
{
  "command": "click",
  "x": 100,
  "y": 200
}
```

### Type Command
```json
{
  "command": "type",
  "text": "Hello, World!"
}
```

### Press Key Command
```json
{
  "command": "press_key",
  "key": "enter"
}
```

### Get Active Window
```json
{
  "command": "get_active_window"
}
```

Response:
```json
{
  "type": "command_response",
  "command": "get_active_window",
  "success": true,
  "window_info": {
    "app_name": "Safari",
    "bundle_id": "com.apple.Safari",
    "pid": 12345,
    "window_title": "SHAIL Documentation",
    "window_x": 100,
    "window_y": 200,
    "window_width": 1920,
    "window_height": 1080
  }
}
```

### Get Element At Coordinates
```json
{
  "command": "get_element_at",
  "x": 500,
  "y": 300
}
```

## Integration Examples

### Direct AccessibilityBridge Usage
```python
import asyncio
import websockets
import json

async def click_via_accessibility(x, y):
    async with websockets.connect('ws://localhost:8766/accessibility') as ws:
        command = {"command": "click", "x": x, "y": y}
        await ws.send(json.dumps(command))
        response = await ws.recv()
        result = json.loads(response)
        return result.get("success", False)
```

### Via Action Executor
```python
import httpx

async def click_button():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8080/action/click",
            json={
                "action_id": "click-123",
                "x": 100,
                "y": 200
            }
        )
        return response.json()
```

### Via UI Twin
```python
from services.ui_twin import UITwinService, ElementSelector

ui_twin = UITwinService()
selector = ElementSelector(role="AXButton", text="Submit")
result = await ui_twin.executeAction(selector, "click")
```

## Configuration

### Environment Variables

**Action Executor:**
- `ACCESSIBILITY_WS_URL`: AccessibilityBridge WebSocket URL (default: `ws://localhost:8766/accessibility`)

**UI Twin:**
- Action Executor URL can be passed to `executeAction()` method (default: `http://localhost:8080`)

## Known Limitations

1. **Key Code Mapping**: The key code mapping in AXController is simplified. For production, use a complete mapping library.

2. **Special Characters**: Type text may not handle all special characters correctly. Enhanced mapping needed.

3. **Modifier Keys**: Press key doesn't support modifier key combinations (Cmd+C, etc.) yet.

4. **Error Recovery**: Limited error recovery if AccessibilityBridge disconnects during action execution.

5. **Coordinate System**: Uses screen coordinates (top-left origin). Ensure coordinates are correct for your display setup.

## Testing Checklist

- [ ] AccessibilityBridge running and accepting connections
- [ ] Click command works via WebSocket
- [ ] Type command works via WebSocket
- [ ] Press key command works via WebSocket
- [ ] Get active window returns correct information
- [ ] Get element at coordinates returns element info
- [ ] Action Executor uses AccessibilityBridge (check logs)
- [ ] Action Executor falls back to PyAutoGUI if needed
- [ ] UI Twin executeAction finds elements and executes actions
- [ ] End-to-end: UI Twin → Action Executor → AccessibilityBridge → UI

## Next Steps

Phase 3 is complete! Ready to proceed with:
- **Phase 4**: Backend WebSocket & LangGraph State
- **Phase 5**: Bird's Eye Graph Visualization
- **Phase 6**: Chat & Detail View Integration (enhancements)

## Troubleshooting

### Click not working
- Check Accessibility permission is granted
- Verify coordinates are correct (screen coordinates)
- Check AccessibilityBridge logs for errors

### Type not working
- Verify text is valid
- Check for special characters that may need special handling
- Ensure target element is focused (may need click first)

### Action Executor not connecting
- Verify AccessibilityBridge is running on port 8766
- Check WebSocket URL in environment variables
- Review Action Executor logs for connection errors

### UI Twin executeAction fails
- Verify element exists in UI Twin (check element list)
- Ensure Action Executor service is running
- Check selector matches element properties correctly

