# Shail AccessibilityBridge

Real-time accessibility monitoring service for macOS using AXUIElement and AXObserver.

## Features

- Real-time focus change monitoring
- Window event tracking (moved, resized, activated)
- UI element inspection (role, title, text, bounding box)
- WebSocket server on `ws://localhost:8766/accessibility`
- Heartbeat messages every 1 second

## Requirements

- macOS 12.0 or later
- Xcode 15.0 or later
- Swift 5.9 or later

## Building

```bash
cd /Users/reyhan/jarvis_master/native/mac/AccessibilityBridge
xcodebuild -project AccessibilityBridge.xcodeproj -scheme AccessibilityBridge -configuration Release
```

Or open `AccessibilityBridge.xcodeproj` in Xcode and build.

## Running

```bash
# From build output
./build/Release/AccessibilityBridge

# Or from Xcode (Cmd+R)
```

## Permissions

On first run, macOS will prompt for Accessibility permission. Grant it in:

**System Preferences > Privacy & Security > Accessibility**

## WebSocket Protocol

### Accessibility Event Messages (JSON)
```json
{
  "type": "accessibility_event",
  "timestamp": "2025-11-13T10:30:00Z",
  "notification_type": "focus_changed",
  "element_id": "uuid-here",
  "app_name": "Safari",
  "bundle_id": "com.apple.Safari",
  "window_title": "Shail - README",
  "role": "AXTextField",
  "title": "Search",
  "text": "screen capture",
  "description": "Search field",
  "x": 100,
  "y": 200,
  "width": 300,
  "height": 40,
  "bbox": [100, 200, 400, 240]
}
```

### Heartbeat Messages (JSON)
```json
{
  "type": "heartbeat",
  "timestamp": "2025-11-13T10:30:00Z",
  "events_captured": 1234,
  "monitoring": true
}
```

## Integration

Python client example:

```python
import asyncio
import websockets
import json

async def monitor_accessibility():
    async with websockets.connect('ws://localhost:8766/accessibility') as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            
            if data['type'] == 'accessibility_event':
                print(f"Focus changed to: {data.get('app_name')} - {data.get('role')}")
                print(f"  Element: {data.get('title', data.get('text', 'N/A'))}")
                print(f"  Position: {data.get('bbox', 'N/A')}")
            elif data['type'] == 'heartbeat':
                print(f"Events captured: {data['events_captured']}")

asyncio.run(monitor_accessibility())
```

## Architecture

- `main.swift`: Entry point, permission check, service initialization
- `AccessibilityBridge.swift`: AXObserver integration, event monitoring
- `AXWebSocketServer.swift`: WebSocket server using Network framework
- `AXPermissionManager.swift`: Accessibility permission handling

## Monitored Events

- `kAXFocusedUIElementChangedNotification`: Element gained focus
- `kAXWindowMovedNotification`: Window position changed
- `kAXWindowResizedNotification`: Window size changed
- Application activation: Active app changed

## License

Part of the Shail AI system.

