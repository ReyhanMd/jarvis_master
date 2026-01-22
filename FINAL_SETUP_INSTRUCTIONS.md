# ✅ Final Setup Instructions - Everything Fixed!

## What's Been Fixed

### 1. ✅ Build Settings
- Added `-parse-as-library` flag for @main support
- Disabled code signing (using ad-hoc signing)
- Disabled app sandbox and hardened runtime for development
- Both projects build successfully

### 2. ✅ Main Entry Points
- Added explicit permission requests at startup
- Added `fflush(stdout)` to ensure console output appears
- Added DispatchGroup to keep apps alive
- Apps won't exit immediately

### 3. ✅ Code Signing
- Changed to ad-hoc signing (`CODE_SIGN_IDENTITY = "-"`)
- Removed development team requirement
- Apps can run without certificates

## How to Run (2 Options)

### OPTION 1: Run from Xcode (Recommended First Time)

1. **Open Xcode projects**:
   ```bash
   ./open_xcode_projects.sh
   ```

2. **In CaptureService window**:
   - Press `⌘ + Shift + K` (Clean)
   - Press `⌘ + B` (Build)
   - Press `⌘ + Shift + Y` (Show console - IMPORTANT!)
   - Press `⌘ + R` (Run)
   
3. **Watch the console** (bottom panel in Xcode):
   ```
   🎥 CaptureService initializing...
   📌 Requesting Screen Recording permission...
   [macOS popup appears]
   ```

4. **Grant permission**:
   - Click "Open System Settings"
   - Enable checkbox for CaptureService
   - Click "Quit & Reopen" or restart app

5. **Do same for AccessibilityBridge**

### OPTION 2: Run from Terminal (Better for Debugging)

After building in Xcode once:

```bash
./run_native_services.sh
```

This opens both services in separate Terminal windows where you can see ALL output.

## Troubleshooting

### "App runs then immediately exits"

**Fix**: Make sure console is visible (`⌘ + Shift + Y` in Xcode)

The app IS running, but:
- Console output might be hidden
- The app is waiting for permission
- Check System Settings to see if popup appeared

### "No permission popup"

**Fix**: Run from Terminal instead:
```bash
# Find the built app
find ~/Library/Developer/Xcode/DerivedData -name "CaptureService" -type f -perm +111 | grep Debug | head -1

# Run it directly
~/Library/Developer/Xcode/DerivedData/CaptureService-*/Build/Products/Debug/CaptureService
```

Terminal shows output immediately and permissions work better.

### "Build failed - signing certificate"

**Fixed**: I've set `CODE_SIGN_IDENTITY = "-"` (ad-hoc signing)

Rebuild in Xcode (`⌘ + Shift + K` then `⌘ + B`)

## What You Should See

### When It Works:

**In Console/Terminal:**
```
🎥 CaptureService initializing...
📍 Check this console for all output!
⏳ App running... waiting for events
📌 Requesting Screen Recording permission...
✅ Screen recording permission GRANTED!
🌐 Starting WebSocket server on port 8765...
📹 Starting screen capture...
🟢 CaptureService LIVE at ws://localhost:8765/capture
📊 Streaming at 30 FPS with JPEG compression
💡 App will run until you press Stop in Xcode
```

**Permission Popup:**
macOS shows: "CaptureService would like to record your screen"
- Click "Open System Settings"
- Enable the checkbox
- Restart the app

## Next Steps

1. **Build both projects** in Xcode (`⌘ + B`)
2. **Show console** (`⌘ + Shift + Y`)
3. **Run** (`⌘ + R`)
4. **Grant permissions** when prompted
5. **See output** in console
6. **Test WebSocket**:
   ```bash
   websocat ws://localhost:8765/capture
   websocat ws://localhost:8766/accessibility
   ```

## Alternative: Build from Command Line

```bash
# Build CaptureService
cd /Users/reyhan/shail_master/native/mac/CaptureService
xcodebuild -project CaptureService.xcodeproj -scheme CaptureService -configuration Debug

# Run it
./DerivedData/CaptureService/Build/Products/Debug/CaptureService

# Or find it
find ~/Library/Developer/Xcode/DerivedData -name "CaptureService" -type f -perm +111 | grep Debug
```

## Success Indicators

✅ Console shows: "🎥 CaptureService initializing..."
✅ Console shows: "⏳ App running... waiting for events"  
✅ macOS shows permission popup
✅ After granting: "✅ Screen recording permission GRANTED!"
✅ WebSocket server starts
✅ Frames stream continuously

The apps are now properly configured to:
- Request permissions at startup
- Stay alive and running
- Show all console output
- Stream data via WebSocket

Try running in Xcode now with console visible (`⌘ + Shift + Y`)!

