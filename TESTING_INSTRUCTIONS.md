# 🧪 Testing Instructions - After Implementation

## ✅ Phase 1 Complete: Direct LLM Chat Endpoint

The `/chat` endpoint has been successfully added! Here's what to test:

## Step 1: Build Projects in Xcode

1. **Open Xcode projects:**
   ```bash
   ./open_xcode_projects.sh
   ```

2. **For each project (CaptureService and AccessibilityBridge):**
   - Press `⌘ + Shift + K` (Clean)
   - Press `⌘ + B` (Build)
   - Verify build succeeds

## Step 2: Set Up Permissions

```bash
./setup_permissions.sh
```

This will:
- Open System Settings to Screen Recording
- Open System Settings to Accessibility
- Guide you through enabling permissions

## Step 3: Start Services

### Start Native Services:
```bash
./run_native_services.sh
```

### Start Python Services:
```bash
./START_PYTHON_SERVICES.sh
```

## Step 4: Test Everything

### 1. Test Screen Capture
```bash
# Run native services
./run_native_services.sh

# In another terminal, connect to WebSocket
websocat ws://localhost:8765/capture
# You should see binary JPEG frames streaming
```

**Expected:** Binary JPEG data streaming continuously

### 2. Test Accessibility
```bash
# Services should already be running from step 1
# In another terminal:
websocat ws://localhost:8766/accessibility
# Then click around your screen, switch windows, etc.
```

**Expected:** JSON events like:
```json
{
  "type": "accessibility_event",
  "app_name": "Safari",
  "window_title": "Google",
  "role": "AXButton",
  "text": "Search"
}
```

### 3. Test Actions (Mouse/Keyboard Control)
```bash
# Test mouse click
curl -X POST http://localhost:8080/action/click \
  -H "Content-Type: application/json" \
  -d '{"action_id": "test1", "x": 500, "y": 300}'

# Test typing
curl -X POST http://localhost:8080/action/type \
  -H "Content-Type: application/json" \
  -d '{"action_id": "test2", "text": "Hello from Shail!"}'
```

**Expected:** Mouse moves and clicks, text types on screen

### 4. Test Vision (OCR)
```bash
# Take a screenshot first (⌘+Shift+4, then space, click window)
# Save it as test.png

# Test OCR
curl -X POST -F "file=@test.png" http://localhost:8081/ocr

# Test full analysis
curl -X POST -F "file=@test.png" http://localhost:8081/analyze
```

**Expected:** JSON with extracted text and bounding boxes

### 5. Test LLM (Direct Chat - NEW!)
```bash
# Test the new /chat endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "What is 2+2? Explain briefly."}'
```

**Expected:** Immediate JSON response:
```json
{
  "text": "2 + 2 equals 4...",
  "model": "gemini-2.0-flash",
  "timestamp": "2025-11-22T..."
}
```

### 6. Test LLM (Async Task Queue - Existing)
```bash
# Submit task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"text": "Write a Python function to calculate factorial"}'

# Get task ID from response, then check status:
curl http://localhost:8000/tasks/{task_id}
```

**Expected:** Task queued, then processed by worker

## Health Checks

### Check Native Services:
```bash
./check_native_health.sh
```

### Check All Services:
```bash
./test_services.sh
```

### Check Integration:
```bash
./test_native_integration.sh
```

## What Should Work

✅ **Screen Capture:** Frames streaming at 30 FPS  
✅ **Accessibility:** Events streaming on focus/window changes  
✅ **Actions:** Mouse and keyboard control working  
✅ **Vision:** OCR extracting text from screenshots  
✅ **LLM Chat:** Direct synchronous conversation (NEW!)  
✅ **LLM Tasks:** Async task processing (existing)  

## What's Not Connected Yet

❌ **Screen → LLM:** Frames not sent to Gemini yet  
❌ **Vision → LLM:** OCR results not routed to LLM  
❌ **End-to-End Tasks:** Planner not fully integrated  

## Next Steps After Testing

Once you've verified everything works:
1. Phase 2: Connect Screen Capture → Vision → LLM
2. Phase 3: Add multimodal image support to /chat
3. Phase 4: Complete end-to-end task execution

## Troubleshooting

### "GEMINI_API_KEY not configured"
- Check `.env` file has `GEMINI_API_KEY=your_key`
- Or export: `export GEMINI_API_KEY=your_key`

### "Port already in use"
- Run: `./stop_native_services.sh`
- Then: `./run_native_services.sh`

### "Permission denied"
- Run: `./setup_permissions.sh`
- Enable checkboxes in System Settings
- Restart services

### "Build failed in Xcode"
- Make sure HealthCheckServer.swift files are in project
- Clean build folder: `⌘ + Shift + K`
- Build again: `⌘ + B`

