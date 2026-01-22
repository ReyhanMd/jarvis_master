# Shail CaptureService

Real-time screen capture service for macOS using ScreenCaptureKit.

## Features

- 30-60 FPS screen capture using ScreenCaptureKit
- JPEG compression for efficient streaming
- WebSocket server on `ws://localhost:8765/capture`
- Automatic permission handling
- Heartbeat messages every 1 second

## Requirements

- macOS 12.3 or later
- Xcode 15.0 or later
- Swift 5.9 or later

## Building

```bash
cd /Users/reyhan/shail_master/native/mac/CaptureService
xcodebuild -project CaptureService.xcodeproj -scheme CaptureService -configuration Release
```

Or open `CaptureService.xcodeproj` in Xcode and build.

## Running

```bash
# From build output
./build/Release/CaptureService

# Or from Xcode (Cmd+R)
```

## Permissions

On first run, macOS will prompt for Screen Recording permission. Grant it in:

**System Preferences > Privacy & Security > Screen Recording**

## WebSocket Protocol

### Frame Messages (Binary)
- JPEG-compressed screen frames
- Sent continuously at 30 FPS
- Downscaled to 1920x1080

### Heartbeat Messages (Text/JSON)
```json
{
  "type": "heartbeat",
  "timestamp": "2025-11-13T10:30:00Z",
  "frames_captured": 1234,
  "uptime_seconds": 60.5
}
```

## Integration

Python client example:

```python
import asyncio
import websockets

async def receive_frames():
    async with websockets.connect('ws://localhost:8765/capture') as ws:
        while True:
            msg = await ws.recv()
            if isinstance(msg, bytes):
                # JPEG frame
                with open('frame.jpg', 'wb') as f:
                    f.write(msg)
            else:
                # JSON heartbeat
                print(msg)

asyncio.run(receive_frames())
```

## Architecture

- `main.swift`: Entry point, permission check, service initialization
- `ScreenCaptureService.swift`: ScreenCaptureKit integration, frame capture
- `WebSocketServer.swift`: WebSocket server using Network framework
- `PermissionManager.swift`: Screen recording permission handling

## License

Part of the Shail AI system.

