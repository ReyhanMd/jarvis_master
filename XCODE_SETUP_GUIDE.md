# Xcode Setup Guide for Native Services

## Why Xcode?

Xcode provides the full macOS SDK needed for:
- **ScreenCaptureKit**: Real-time screen capture (30-60 FPS)
- **ApplicationServices**: Accessibility event monitoring
- **Native performance**: Swift apps run faster than Python

## Installation Steps

### Step 1: Install Xcode

1. **Open App Store** on your Mac
2. **Search for "Xcode"**
3. **Click "Get" or "Install"** (it's free!)
4. **Wait for download** (~12GB, takes 30-60 minutes)

### Step 2: Configure Xcode

After installation completes:

```bash
# Set Xcode as active developer directory
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer

# Accept Xcode license
sudo xcodebuild -license accept

# Verify it's working
xcodebuild -version
```

You should see:
```
Xcode 15.0
Build version 15A240d
```

### Step 3: Build Native Services

```bash
cd /Users/reyhan/shail_master

# This will automatically build native services
./START_NATIVE_SERVICES.sh
```

The script will:
1. Build `CaptureService` (Swift)
2. Build `AccessibilityBridge` (Swift)
3. Start all services (native + Python)

### Step 4: Grant Permissions

On first run, macOS will prompt for permissions:

#### Screen Recording Permission
1. System Preferences → Privacy & Security → Screen Recording
2. Enable **CaptureService**
3. Restart the service if needed

#### Accessibility Permission
1. System Preferences → Privacy & Security → Accessibility
2. Enable **AccessibilityBridge**
3. Restart the service if needed

## What You'll Get

### With Native Services Running:

```
┌─────────────────────────────────────┐
│  Native Services (Swift)            │
│  ✅ CaptureService (30-60 FPS)      │
│  ✅ AccessibilityBridge (events)    │
└──────────────┬──────────────────────┘
               │ WebSocket streams
┌──────────────▼──────────────────────┐
│  Python Services                     │
│  ✅ UI Twin (live element graph)    │
│  ✅ Real-time vision processing     │
│  ✅ Automatic action execution      │
└─────────────────────────────────────┘
```

### Features Enabled:

1. **Real-time Screen Capture**
   - 30-60 frames per second
   - JPEG compression
   - WebSocket streaming to `ws://localhost:8765`

2. **Real-time Accessibility Events**
   - Focus changes
   - Window events
   - UI element updates
   - WebSocket streaming to `ws://localhost:8766`

3. **UI Twin Live Tracking**
   - Real-time element graph
   - Automatic element discovery
   - Temporal buffer of UI history

## Troubleshooting

### "xcode-select: error: tool 'xcodebuild' requires Xcode"

**Solution:**
```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

### "Xcode license agreement"

**Solution:**
```bash
sudo xcodebuild -license accept
```

### Build Errors

If you see build errors:
1. Open Xcode once to complete setup
2. Run: `xcodebuild -checkFirstLaunchStatus`
3. Try building again

### Permission Denied

If services can't capture screen:
1. System Preferences → Privacy & Security → Screen Recording
2. Make sure CaptureService is enabled
3. Restart the service

## Testing Native Services

After starting, test the WebSocket streams:

```bash
# Install websocat (if not already)
brew install websocat

# Test CaptureService
websocat ws://localhost:8765/capture

# Test AccessibilityBridge
websocat ws://localhost:8766/accessibility
```

You should see:
- **CaptureService**: JPEG frames (binary) + JSON heartbeats
- **AccessibilityBridge**: JSON events when you interact with UI

## Performance

With native services:
- **Screen capture**: 30-60 FPS (vs manual screenshots)
- **Event latency**: < 50ms (vs polling)
- **CPU usage**: Lower (native Swift vs Python)

## Next Steps

1. ✅ Install Xcode
2. ✅ Configure Xcode
3. ✅ Run `./START_NATIVE_SERVICES.sh`
4. ✅ Grant permissions
5. ✅ Test WebSocket streams
6. ✅ Enjoy full automation! 🚀

