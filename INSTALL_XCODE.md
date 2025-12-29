# Installing Xcode for Native Services

## Quick Steps

### 1. Install Xcode from App Store
- Open **App Store** on your Mac
- Search for **"Xcode"**
- Click **"Get"** or **"Install"** (it's free!)
- Wait for download (~12GB, may take 30-60 minutes)

### 2. After Installation

```bash
# Set Xcode as active developer directory
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer

# Accept Xcode license
sudo xcodebuild -license accept

# Verify it's working
xcodebuild -version
```

You should see something like:
```
Xcode 15.0
Build version 15A240d
```

### 3. Build Native Services

```bash
cd /Users/reyhan/jarvis_master

# This will now automatically build native services
./START_NATIVE_SERVICES.sh
```

## What Xcode Provides

- **ScreenCaptureKit**: Real-time screen capture (30-60 FPS)
- **ApplicationServices**: Accessibility event monitoring
- **Full macOS SDK**: All frameworks needed for native apps
- **Code signing**: Required for certain macOS features

## Troubleshooting

### "xcode-select: error: tool 'xcodebuild' requires Xcode"
- Make sure Xcode is fully installed (not just downloading)
- Run: `sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer`

### "Xcode license agreement"
- Run: `sudo xcodebuild -license accept`

### "Command Line Tools" vs "Xcode"
- Command Line Tools: Basic compilers (what you have now)
- Xcode: Full IDE + SDK (what you need for native services)

## After Installing Xcode

Once Xcode is installed and configured:

1. **Native services will build automatically** when you run `./START_NATIVE_SERVICES.sh`
2. **You'll get real-time screen capture** at 30-60 FPS
3. **You'll get accessibility events** in real-time
4. **UI Twin will track elements** automatically

## Alternative: Test Without Xcode First

You can test all Python services without Xcode:

```bash
./START_PYTHON_SERVICES.sh
```

This works for:
- Action Executor (click, type, scroll)
- Vision (OCR on screenshots)
- RAG Retriever (document search)
- Planner (task orchestration)

You just won't have real-time screen capture and accessibility events.

