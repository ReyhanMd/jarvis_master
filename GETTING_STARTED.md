# Getting Started with Shail Native Services

## 🎉 Implementation Complete!

All native services and AI orchestration components have been created and are ready to use.

## 📋 Quick Start (5 minutes)

### 1. Make Scripts Executable

```bash
cd /Users/reyhan/shail_master
chmod +x START_NATIVE_SERVICES.sh STOP_NATIVE_SERVICES.sh
```

### 2. Set API Keys (Optional)

```bash
# For LLM-based planning (GPT-4)
export OPENAI_API_KEY=your-openai-key

# For Vision-Language Models (Claude)
export ANTHROPIC_API_KEY=your-anthropic-key
```

### 3. Start All Services

```bash
./START_NATIVE_SERVICES.sh
```

This script will:
- Build native services if needed (macOS)
- Create Python virtual environment
- Install all dependencies
- Start all 7 services
- Show you the status and PIDs

### 4. Verify Services are Running

```bash
# Check Action Executor
curl http://localhost:8080/health

# Check Vision
curl http://localhost:8081/health

# Check RAG Retriever
curl http://localhost:8082/health

# Check Planner
curl http://localhost:8083/health
```

### 5. Execute Your First Task

Create a test file `test_shail.py`:

```python
import httpx
import asyncio
import json

async def test_task():
    async with httpx.AsyncClient() as client:
        # Create and execute a simple task
        response = await client.post(
            "http://localhost:8083/execute",
            json={
                "task_id": "test-001",
                "description": "Open Safari browser",
                "timeout_seconds": 60
            },
            timeout=120.0
        )
        
        result = response.json()
        
        print("Task Execution Result:")
        print(json.dumps(result, indent=2))
        
        if result.get("success"):
            print("\n✅ Task completed successfully!")
        else:
            print("\n❌ Task failed:", result.get("result_summary"))

if __name__ == "__main__":
    asyncio.run(test_task())
```

Run it:

```bash
python test_shail.py
```

### 6. Stop Services When Done

```bash
./STOP_NATIVE_SERVICES.sh
```

## 🗂️ What Was Created

### Native Layer (Swift/C#)

#### macOS
- **CaptureService**: 30-60 FPS screen capture with ScreenCaptureKit
  - Location: `native/mac/CaptureService/`
  - WebSocket: `ws://localhost:8765/capture`
  
- **AccessibilityBridge**: Real-time UI event monitoring
  - Location: `native/mac/AccessibilityBridge/`
  - WebSocket: `ws://localhost:8766/accessibility`

#### Windows (Placeholder)
- **CaptureService**: Desktop Duplication API structure
  - Location: `native/win/CaptureService/`
  
- **UIAutomationBridge**: UI Automation API structure
  - Location: `native/win/UIAutomationBridge/`

### Python Services

1. **UI Twin** (Port: Background WebSocket consumer)
   - Real-time UI state tracking
   - Element graph maintenance
   - Location: `services/ui_twin/`

2. **Action Executor** (Port: 8080)
   - Click, type, scroll actions
   - Safety verification
   - Location: `services/action_executor/`

3. **Vision** (Port: 8081)
   - OCR text extraction
   - VLM screen description
   - Location: `services/vision/`

4. **RAG Retriever** (Port: 8082)
   - Context retrieval
   - Vector search
   - Location: `services/rag_retriever/`

5. **Planner** (Port: 8083)
   - Task orchestration
   - LangGraph workflows
   - Location: `services/planner/`

## 📚 Documentation

Comprehensive documentation is available:

- **System Overview**: `NATIVE_SERVICES_README.md`
- **Implementation Details**: `IMPLEMENTATION_COMPLETE.md`
- **Service-Specific**: Each service has its own `README.md`

## 🔧 Troubleshooting

### Native Services Not Starting (macOS)

**Problem**: "Screen Recording permission required"

**Solution**:
1. Open System Preferences
2. Go to Privacy & Security > Screen Recording
3. Add and enable CaptureService
4. Restart the service

**Problem**: "Accessibility permission required"

**Solution**:
1. Open System Preferences
2. Go to Privacy & Security > Accessibility
3. Add and enable AccessibilityBridge
4. Restart the service

### Python Services Not Starting

**Problem**: "Module not found"

**Solution**:
```bash
# Activate virtual environment
source services_env/bin/activate

# Install dependencies for specific service
cd services/[service_name]
pip install -r requirements.txt
```

**Problem**: "Port already in use"

**Solution**:
```bash
# Find and kill process using the port
lsof -ti:8080 | xargs kill -9  # Replace 8080 with your port
```

### LLM Features Not Working

**Problem**: "langchain not installed"

**Solution**:
```bash
cd services/planner
pip install -r requirements.txt
```

**Problem**: "API key not set"

**Solution**:
```bash
export OPENAI_API_KEY=your-key
# or add to ~/.zshrc for persistence
```

## 🧪 Testing Individual Components

### Test CaptureService (macOS)

```bash
# Install websocat for testing
brew install websocat

# Connect to capture stream
websocat ws://localhost:8765/capture

# You should see JPEG frames (binary data) and JSON heartbeats
```

### Test AccessibilityBridge (macOS)

```bash
# Connect to accessibility stream
websocat ws://localhost:8766/accessibility

# Focus different windows/apps - you should see JSON events
```

### Test Action Executor

```bash
# Execute a click action
curl -X POST http://localhost:8080/action/click \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "test-1",
    "x": 500,
    "y": 500
  }'
```

### Test Vision Service

```bash
# Take a screenshot and analyze it
screencapture -x /tmp/test.png

curl -X POST http://localhost:8081/ocr \
  -F "file=@/tmp/test.png"
```

### Test RAG Retriever

```bash
# Index a document
curl -X POST http://localhost:8082/index \
  -H "Content-Type: application/json" \
  -d '{
    "id": "doc-1",
    "content": "Git is a version control system",
    "namespace": "git_docs",
    "metadata": {}
  }'

# Retrieve similar documents
curl -X POST http://localhost:8082/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is git?",
    "namespace": "git_docs",
    "top_k": 3
  }'
```

### Test Planner

```bash
# Create and execute a plan
curl -X POST http://localhost:8083/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-123",
    "description": "Open the calculator app"
  }'
```

## 📊 Monitoring

### View Logs

```bash
# All logs are in logs/ directory
tail -f logs/planner.log
tail -f logs/action_executor.log
tail -f logs/vision.log
tail -f logs/rag_retriever.log
tail -f logs/ui_twin.log
tail -f logs/capture_service.log
tail -f logs/accessibility_bridge.log
```

### Check Process Status

```bash
# See all running services
ps aux | grep -E "(CaptureService|AccessibilityBridge|service.py)"
```

### Monitor WebSocket Streams

```bash
# Install websocat if not already
brew install websocat

# Monitor capture stream
websocat ws://localhost:8765/capture | head -100

# Monitor accessibility stream
websocat ws://localhost:8766/accessibility
```

## 🚀 Next Steps

1. **Try Complex Tasks**: Test multi-step tasks through the planner
2. **Add Documentation**: Index your own documentation in RAG
3. **Custom Actions**: Add new action types to the executor
4. **Vision Models**: Integrate GPT-4V or Claude Vision
5. **Windows Support**: Complete the C# implementations
6. **UI Dashboard**: Build a monitoring dashboard

## 📖 Learn More

- Read `NATIVE_SERVICES_README.md` for architecture details
- Check individual service READMEs for specific features
- See `IMPLEMENTATION_COMPLETE.md` for what was built

## 🎯 Example Use Cases

### 1. Git Workflow Automation
```python
task = {
    "task_id": "git-001",
    "description": "Create a new git commit with message 'Initial commit'"
}
```

### 2. Browser Automation
```python
task = {
    "task_id": "browser-001",
    "description": "Open Safari, navigate to github.com, and search for 'langchain'"
}
```

### 3. Document Analysis
```python
task = {
    "task_id": "doc-001",
    "description": "Take a screenshot of the current window and extract all text"
}
```

## ✅ Success Criteria

You'll know everything is working when:

1. ✅ All 7 services start without errors
2. ✅ Health checks return `{"status": "ok"}`
3. ✅ You can execute a simple task via the planner
4. ✅ Logs show real-time events and actions
5. ✅ WebSocket streams are sending data

## 🎉 You're Ready!

The entire Shail native services system is now set up and ready to use. Start with simple tasks and gradually increase complexity as you get familiar with the system.

Happy automating! 🚀

