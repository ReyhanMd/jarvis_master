# Shail CaptureService (Windows)

Real-time screen capture service for Windows using Desktop Duplication API.

## Status

⚠️ **Placeholder Implementation** - Requires completion

## Features (Planned)

- 30-60 FPS screen capture using Desktop Duplication API (SharpDX)
- JPEG compression for efficient streaming
- WebSocket server on `ws://localhost:8765/capture`
- Heartbeat messages every 1 second

## Requirements

- Windows 10 version 1903 or later
- .NET 6.0 or later
- Visual Studio 2022 (recommended)

## Building

```powershell
cd native\win\CaptureService
dotnet build -c Release
```

Or open `CaptureService.csproj` in Visual Studio and build.

## Implementation Notes

### Desktop Duplication API (Recommended)
Use SharpDX to access DirectX Desktop Duplication API for high-performance capture:

```csharp
using SharpDX.DXGI;
using SharpDX.Direct3D11;

// Initialize
var factory = new Factory1();
var adapter = factory.GetAdapter1(0);
var device = new Device(adapter);
var output = adapter.GetOutput(0);
var output1 = output.QueryInterface<Output1>();
var duplication = output1.DuplicateOutput(device);

// Capture frame
duplication.AcquireNextFrame(1000, out var frameInfo, out var desktopResource);
```

### Windows.Graphics.Capture (Alternative)
Use Windows.Graphics.Capture for easier integration but slightly lower performance:

```csharp
var item = await CaptureHelper.CreateItemForMonitor(primaryMonitor);
var framePool = Direct3D11CaptureFramePool.Create(...);
framePool.FrameArrived += OnFrameArrived;
```

## WebSocket Protocol

Same as macOS version - see `native/mac/CaptureService/README.md`

## License

Part of the Shail AI system.

