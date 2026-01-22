# Building Native Services - Step by Step Guide

## ✅ STEP 1 — Open CaptureService Xcode Project

### Option A: From Terminal
```bash
cd /Users/reyhan/shail_master/native/mac/CaptureService
open CaptureService.xcodeproj
```

### Option B: From Finder
1. Navigate to: `/Users/reyhan/shail_master/native/mac/CaptureService/`
2. Double-click: `CaptureService.xcodeproj`

Xcode will open the project.

## ✅ STEP 2 — Build CaptureService in Xcode

### In Xcode:
1. **Select Scheme**: Make sure "CaptureService" is selected in the scheme dropdown (top toolbar)
2. **Select Target**: Product → Destination → My Mac
3. **Build**: Press `⌘ + B` (or Product → Build)
4. **Run**: Press `⌘ + R` (or Product → Run)

### What to Expect:
- Xcode will compile the Swift code
- The app will launch
- You'll see output in Xcode's console:
  ```
  🎥 Shail CaptureService starting...
  ✅ CaptureService running on ws://localhost:8765/capture
  📊 Streaming at 30 FPS with JPEG compression
  ```

### If You See Permission Prompts:
- **Screen Recording**: Click "Open System Settings" → Enable for CaptureService
- **Accessibility**: Click "Open System Settings" → Enable for CaptureService

## ✅ STEP 3 — Open AccessibilityBridge Xcode Project

### From Terminal:
```bash
cd /Users/reyhan/shail_master/native/mac/AccessibilityBridge
open AccessibilityBridge.xcodeproj
```

### In Xcode:
1. **Select Scheme**: "AccessibilityBridge"
2. **Build**: `⌘ + B`
3. **Run**: `⌘ + R`

### What to Expect:
```
♿ Shail AccessibilityBridge starting...
✅ AccessibilityBridge running on ws://localhost:8766/accessibility
📡 Monitoring focus changes, window events, and UI interactions
```

## ✅ STEP 4 — Grant macOS Permissions

### Manual Setup (if not prompted):

1. **System Settings → Privacy & Security → Screen Recording**
   - Enable: `CaptureService`

2. **System Settings → Privacy & Security → Accessibility**
   - Enable: `AccessibilityBridge`
   - Enable: `Terminal` (optional but recommended)

3. **System Settings → Privacy & Security → Developer Tools**
   - Enable: `Xcode` (if not already)

### Verify Permissions:
```bash
# Check Screen Recording
tccutil reset ScreenCapture com.shail.CaptureService

# Check Accessibility
tccutil reset Accessibility com.shail.AccessibilityBridge
```

## ✅ STEP 5 — Start Python Services

In a **new terminal window** (keep Xcode running):

```bash
cd /Users/reyhan/shail_master
./START_NATIVE_SERVICES.sh
```

This will:
- Skip building native services (already running from Xcode)
- Start all Python services
- Connect to the native services via WebSocket

## ✅ STEP 6 — Test the Full System

### Test Native Services (WebSocket):
```bash
# Install websocat if needed
brew install websocat

# Test CaptureService
websocat ws://localhost:8765/capture

# Test AccessibilityBridge (in another terminal)
websocat ws://localhost:8766/accessibility
```

### Test Python Services:
```bash
# Health checks
curl http://localhost:8080/health  # Action Executor
curl http://localhost:8081/health  # Vision
curl http://localhost:8082/health  # RAG Retriever
curl http://localhost:8083/health  # Planner

# Or use the test script
./test_services.sh
```

## ✅ STEP 7 — Verify End-to-End Connection

### Check UI Twin is Receiving Events:
```bash
tail -f logs/ui_twin.log
```

You should see:
```
📡 Connected to AccessibilityBridge at ws://localhost:8766/accessibility
📝 Updated element ...: AXButton in Safari
```

### Check Vision is Receiving Frames:
```bash
tail -f logs/vision.log
```

## 🎉 Success Indicators

You'll know everything is working when:

1. ✅ **Xcode Console** shows:
   - `[CaptureService] Frame streamed`
   - `[AccessibilityBridge] Focus changed`

2. ✅ **Python Services** show:
   - `[UI Twin] Received AX event`
   - `[Planner] Ready on port 8083`

3. ✅ **WebSocket Streams** are active:
   - CaptureService sending frames
   - AccessibilityBridge sending events

4. ✅ **Health Checks** return:
   - All services: `{"status":"ok"}`

## 🔄 Running in Background (Optional)

Once everything works, you can run native services in background:

```bash
# Build Release versions
cd /Users/reyhan/shail_master/native/mac/CaptureService
xcodebuild -project CaptureService.xcodeproj -scheme CaptureService -configuration Release

cd ../AccessibilityBridge
xcodebuild -project AccessibilityBridge.xcodeproj -scheme AccessibilityBridge -configuration Release

# Then run from command line
./build/Release/CaptureService &
./build/Release/AccessibilityBridge &
```

## 🐛 Troubleshooting

### "Permission Denied"
- Go to System Settings → Privacy & Security
- Enable Screen Recording and Accessibility
- Restart the services

### "Port Already in Use"
```bash
# Find what's using the port
lsof -i :8765
lsof -i :8766

# Kill it
kill -9 <PID>
```

### "Build Failed"
- Make sure Xcode is fully installed
- Run: `sudo xcodebuild -license accept`
- Clean build: `⌘ + Shift + K` then `⌘ + B`

### "WebSocket Connection Failed"
- Make sure native services are running in Xcode
- Check they're listening on ports 8765 and 8766
- Verify firewall isn't blocking localhost

## 🚀 Next Steps

Once everything is connected:

1. **Test a Real Task**:
   ```bash
   curl -X POST http://localhost:8083/execute \
     -H "Content-Type: application/json" \
     -d '{"task_id": "test-1", "description": "Open Calculator"}'
   ```
3
2. **Monitor the System**:
   ```bash
   # Watch all logs
   tail -f logs/*.log
   ```

3. **Enjoy Your AI Agent!** 🎉

