# Running Native Services Directly from Terminal

## Problem
Xcode console not showing output and apps exit immediately.

## Solution: Run from Terminal Instead

### Build once in Xcode
```bash
cd /Users/reyhan/jarvis_master/native/mac/CaptureService
xcodebuild -project CaptureService.xcodeproj -scheme CaptureService -configuration Debug

cd ../AccessibilityBridge
xcodebuild -project AccessibilityBridge.xcodeproj -scheme AccessibilityBridge -configuration Debug
```

### Find the Built Executables
```bash
# They're in DerivedData folder
find ~/Library/Developer/Xcode/DerivedData -name "CaptureService" -type f -perm +111 2>/dev/null | grep -v ".dSYM"

find ~/Library/Developer/Xcode/DerivedData -name "AccessibilityBridge" -type f -perm +111 2>/dev/null | grep -v ".dSYM"
```

### Run from Terminal
```bash
# Run CaptureService
~/Library/Developer/Xcode/DerivedData/CaptureService-*/Build/Products/Debug/CaptureService

# In another terminal, run AccessibilityBridge
~/Library/Developer/Xcode/DerivedData/AccessibilityBridge-*/Build/Products/Debug/AccessibilityBridge
```

### Why This Works Better
- Console output is VISIBLE in terminal
- Permission prompts appear properly
- You can see exactly what's happening
- App stays running (Ctrl+C to stop)
- Easier to debug

### Expected Output

**CaptureService:**
```
🎥 CaptureService initializing...
📍 Check this console for all output!
📌 Requesting Screen Recording permission...
[macOS shows permission popup]
✅ Screen recording permission GRANTED!
🌐 Starting WebSocket server on port 8765...
📹 Starting screen capture...
🟢 CaptureService LIVE at ws://localhost:8765/capture
📊 Streaming at 30 FPS with JPEG compression
```

**AccessibilityBridge:**
```
♿ AccessibilityBridge initializing...
📍 Check this console for all output!
📌 Requesting Accessibility permission...
[macOS shows permission popup]
✅ Accessibility permission granted!
🌐 Starting WebSocket server on port 8766...
📡 Starting accessibility monitoring...
🟢 AccessibilityBridge LIVE at ws://localhost:8766/accessibility
📊 Monitoring focus changes and window events
```

### Grant Permissions

When apps run from terminal, macOS will show popups:
1. Click "Open System Settings"
2. Enable the checkbox for the executable
3. Restart the app

### Test After Running
```bash
# In another terminal
curl http://localhost:8765  # Should connect (or timeout waiting for WebSocket upgrade)
curl http://localhost:8766  # Should connect

# Or use websocat
brew install websocat
websocat ws://localhost:8765/capture
websocat ws://localhost:8766/accessibility
```

### Make It Easier

Create launch scripts:

```bash
# Create launcher
cat > /Users/reyhan/jarvis_master/run_capture.sh << 'EOF'
#!/bin/bash
EXEC=$(find ~/Library/Developer/Xcode/DerivedData -name "CaptureService" -type f -perm +111 2>/dev/null | grep -v ".dSYM" | head -1)
if [ -z "$EXEC" ]; then
    echo "❌ CaptureService not built yet. Build in Xcode first."
    exit 1
fi
echo "▶️  Running: $EXEC"
"$EXEC"
EOF

chmod +x /Users/reyhan/jarvis_master/run_capture.sh

# Then just run:
./run_capture.sh
```

