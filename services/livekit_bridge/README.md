# LiveKit Bridge Service

Bridges screen capture frames from CaptureService to LiveKit room for vision processing.

## Overview

This service connects to:
- **CaptureService WebSocket** (`ws://localhost:8765/capture`) - Receives JPEG frames
- **LiveKit Room** (`shail-vision`) - Publishes frames as video track

The Vision service can then subscribe to the LiveKit room to process frames in real-time.

## Setup

### 1. Install LiveKit Server

**Option A: Docker (Recommended)**
```bash
docker run --rm \
  -p 7880:7880 \
  -p 7881:7881 \
  -p 7882:7882/udp \
  -e LIVEKIT_KEYS="devkey: devsecret" \
  livekit/livekit-server --dev
```

**Option B: Binary**
```bash
# Download from https://github.com/livekit/livekit/releases
# Or use Homebrew on macOS:
brew install livekit
livekit-server --dev
```

### 2. Set Environment Variables

```bash
export LIVEKIT_URL="ws://localhost:7880"
export LIVEKIT_API_KEY="devkey"
export LIVEKIT_API_SECRET="devsecret"
```

Or create a `.env` file:
```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret
```

### 3. Install Dependencies

```bash
cd services/livekit_bridge
pip install -r requirements.txt
```

### 4. Run the Bridge

```bash
python service.py
```

## Architecture

```
CaptureService (WebSocket) → LiveKit Bridge → LiveKit Room → Vision Service
     Port 8765                    Service          shail-vision    (subscribes)
```

## Configuration

The bridge can be configured via environment variables:

- `CAPTURE_WS_URL`: CaptureService WebSocket URL (default: `ws://localhost:8765/capture`)
- `LIVEKIT_URL`: LiveKit server URL (default: `ws://localhost:7880`)
- `LIVEKIT_API_KEY`: LiveKit API key
- `LIVEKIT_API_SECRET`: LiveKit API secret
- `LIVEKIT_ROOM`: Room name (default: `shail-vision`)

## Integration

### With Vision Service

The Vision service subscribes to the LiveKit room to receive frames:

```python
from livekit import rtc, api

# Connect to room
room = rtc.Room()
token = api.AccessToken(api_key, api_secret) \
    .with_identity("vision-service") \
    .with_grants(api.VideoGrants(
        room_join=True,
        room="shail-vision",
        can_subscribe=True
    ))

await room.connect(livekit_url, token.to_jwt())

# Subscribe to video track
@room.on("track_subscribed")
def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
    if track.kind == rtc.TrackKind.KIND_VIDEO:
        # Process video frames
        pass
```

## Troubleshooting

### Connection Issues

1. **Cannot connect to CaptureService**: Ensure CaptureService is running on port 8765
2. **Cannot connect to LiveKit**: Ensure LiveKit server is running and credentials are correct
3. **Permission errors**: Check that API key and secret are set correctly

### Performance

- Frame rate: 30 FPS (from CaptureService)
- Latency: ~100-200ms (WebSocket + LiveKit processing)
- Bandwidth: ~5-10 Mbps (JPEG compression)

## Development

For development, use LiveKit's dev mode:
```bash
livekit-server --dev
```

This automatically creates API keys: `devkey` / `devsecret`

