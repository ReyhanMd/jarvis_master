# Quick Start: Building Native Services with Xcode

## 🎯 Fastest Path to Success

### 1. Open Both Projects (One Command)
```bash
./open_xcode_projects.sh
```

This opens both Xcode projects automatically.

### 2. Build & Run in Xcode

**In CaptureService project:**
- Press `⌘ + R` (or click the Play button)
- Grant Screen Recording permission when prompted
- You should see: `✅ CaptureService running on ws://localhost:8765/capture`

**In AccessibilityBridge project:**
- Press `⌘ + R`
- Grant Accessibility permission when prompted
- You should see: `✅ AccessibilityBridge running on ws://localhost:8766/accessibility`

### 3. Start Python Services
```bash
./START_NATIVE_SERVICES.sh
```

### 4. Test Everything
```bash
./test_services.sh
```

## ✅ Success Checklist

- [ ] CaptureService running in Xcode (port 8765)
- [ ] AccessibilityBridge running in Xcode (port 8766)
- [ ] Python services started (ports 8080-8083)
- [ ] All health checks pass
- [ ] UI Twin receiving events
- [ ] Vision receiving frames

## 🎉 You're Done!

Your Shail system is now fully operational with:
- Real-time screen capture (30-60 FPS)
- Real-time accessibility events
- Full AI orchestration
- Complete automation capabilities

See `BUILD_NATIVE_SERVICES.md` for detailed troubleshooting.

