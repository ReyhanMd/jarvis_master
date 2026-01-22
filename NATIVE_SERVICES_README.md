# Shail Native Services & Real-Time AI Orchestration

Complete implementation of the real-time system layer with native services and AI orchestration.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / LLM Agent                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                    services/planner/                             │
│              (LangGraph Orchestration)                           │
│    • RAG-enhanced planning                                       │
│    • Step-by-step execution                                      │
│    • Failure recovery & replanning                               │
└─────┬──────────────┬──────────────┬───────────────┬─────────────┘
      │              │              │               │
      ↓              ↓              ↓               ↓
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│ ui_twin  │  │  action  │  │ vision   │  │ rag_retriever│
│          │  │ executor │  │          │  │              │
│ • Graph  │  │ • Click  │  │ • OCR    │  │ • Context    │
│ • Lookup │  │ • Type   │  │ • VLM    │  │ • Docs       │
│ • State  │  │ • Verify │  │ • Detect │  │ • Memory     │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────────┘
     │             │             │
     ↓             ↓             ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Native Layer (Real-Time)                        │
│                                                                   │
│  macOS:                          Windows:                        │
│  ┌──────────────────────┐       ┌──────────────────────┐        │
│  │ CaptureService       │       │ CaptureService       │        │
│  │ • ScreenCaptureKit   │       │ • Desktop Dup API    │        │
│  │ • 30-60 FPS          │       │ • 30-60 FPS          │        │
│  │ • JPEG compression   │       │ • JPEG compression   │        │
│  │ • WebSocket stream   │       │ • WebSocket stream   │        │
│  └──────────────────────┘       └──────────────────────┘        │
│                                                                   │
│  ┌──────────────────────┐       ┌──────────────────────┐        │
│  │ AccessibilityBridge  │       │ UIAutomationBridge   │        │
│  │ • AXUIElement        │       │ • UI Automation API  │        │
│  │ • AXObserver events  │       │ • Focus tracking     │        │
│  │ • Element inspection │       │ • Window events      │        │
│  │ • WebSocket stream   │       │ • WebSocket stream   │        │
│  └──────────────────────┘       └──────────────────────┘        │
│                                                                   │
│  ws://localhost:8765/capture    ws://localhost:8765/capture     │
│  ws://localhost:8766/accessibility  ws://localhost:8766/...     │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
shail_master/
│
├── shail/                    # Existing Python agents + router
│
├── native/                   # NEW — Native system layer
│   ├── mac/
│   │   ├── CaptureService/
│   │   │   ├── main.swift
│   │   │   ├── ScreenCaptureService.swift
│   │   │   ├── WebSocketServer.swift
│   │   │   ├── PermissionManager.swift
│   │   │   ├── CaptureService.xcodeproj/
│   │   │   ├── Info.plist
│   │   │   ├── CaptureService.entitlements
│   │   │   └── README.md
│   │   │
│   │   └── AccessibilityBridge/
│   │       ├── main.swift
│   │       ├── AccessibilityBridge.swift
│   │       ├── AXWebSocketServer.swift
│   │       ├── AXPermissionManager.swift
│   │       ├── AccessibilityBridge.xcodeproj/
│   │       ├── Info.plist
│   │       ├── AccessibilityBridge.entitlements
│   │       └── README.md
│   │
│   └── win/
│       ├── CaptureService/
│       │   ├── Program.cs
│       │   ├── CaptureService.csproj
│       │   └── README.md
│       │
│       └── UIAutomationBridge/
│           ├── Program.cs
│           ├── UIAutomationBridge.csproj
│           └── README.md
│
└── services/                 # NEW — AI orchestration services
    ├── ui_twin/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── service.py
    │   ├── requirements.txt
    │   └── README.md
    │
    ├── action_executor/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── service.py
    │   ├── executors/
    │   │   ├── __init__.py
    │   │   ├── macos.py
    │   │   └── windows.py
    │   ├── requirements.txt
    │   └── README.md
    │
    ├── vision/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── service.py
    │   ├── requirements.txt
    │   └── README.md
    │
    ├── rag_retriever/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── service.py
    │   ├── requirements.txt
    │   └── README.md
    │
    └── planner/
        ├── __init__.py
        ├── models.py
        ├── service.py
        ├── graph.py
        ├── requirements.txt
        └── README.md
```

## Quick Start

### 1. Build Native Services (macOS)

```bash
# CaptureService
cd native/mac/CaptureService
xcodebuild -project CaptureService.xcodeproj \
           -scheme CaptureService \
           -configuration Release

# AccessibilityBridge
cd ../AccessibilityBridge
xcodebuild -project AccessibilityBridge.xcodeproj \
           -scheme AccessibilityBridge \
           -configuration Release
```

### 2. Grant Permissions

**macOS:**
- System Preferences > Privacy & Security > Screen Recording
- System Preferences > Privacy & Security > Accessibility

**Windows:**
- No special permissions required for basic functionality

### 3. Start Native Services

```bash
# Terminal 1: CaptureService
cd native/mac/CaptureService/build/Release
./CaptureService

# Terminal 2: AccessibilityBridge
cd native/mac/AccessibilityBridge/build/Release
./AccessibilityBridge
```

### 4. Install Python Service Dependencies

```bash
# Create virtual environment
python -m venv services_env
source services_env/bin/activate

# Install each service
cd services/ui_twin && pip install -r requirements.txt && cd ../..
cd services/action_executor && pip install -r requirements.txt && cd ../..
cd services/vision && pip install -r requirements.txt && cd ../..
cd services/rag_retriever && pip install -r requirements.txt && cd ../..
cd services/planner && pip install -r requirements.txt && cd ../..
```

### 5. Start Python Services

```bash
# Terminal 3: UI Twin
cd services/ui_twin
python service.py

# Terminal 4: Action Executor
cd services/action_executor
python service.py

# Terminal 5: Vision
cd services/vision
python service.py

# Terminal 6: RAG Retriever
cd services/rag_retriever
python service.py

# Terminal 7: Planner
cd services/planner
export OPENAI_API_KEY=your-key
python service.py
```

### 6. Test the System

```python
import httpx
import asyncio

async def test_system():
    # Execute a task
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8083/execute",
            json={
                "task_id": "test-1",
                "description": "Open Safari and go to google.com"
            },
            timeout=300.0
        )
        
        result = response.json()
        print(f"Status: {result['status']}")
        print(f"Result: {result['result_summary']}")

asyncio.run(test_system())
```

## Service Ports

| Service            | Port | Protocol |
|--------------------|------|----------|
| CaptureService     | 8765 | WebSocket |
| AccessibilityBridge| 8766 | WebSocket |
| Action Executor    | 8080 | HTTP |
| Vision             | 8081 | HTTP |
| RAG Retriever      | 8082 | HTTP |
| Planner            | 8083 | HTTP |

## Data Flow

### 1. Screen Capture Flow
```
User Desktop
    ↓ (30-60 FPS)
CaptureService (Swift/C#)
    ↓ (JPEG frames via WebSocket)
UI Twin Service
    ↓ (on-demand)
Vision Service
    ↓ (OCR + VLM)
Planner
```

### 2. Accessibility Flow
```
User Interaction
    ↓ (focus changes, clicks, etc)
AccessibilityBridge (Swift/C#)
    ↓ (JSON events via WebSocket)
UI Twin Service
    ↓ (element graph updates)
Action Executor (element lookup)
```

### 3. Task Execution Flow
```
User Task
    ↓
Planner Service
    ↓ (retrieve context)
RAG Retriever
    ↓ (generate plan)
Planner + LLM
    ↓ (execute steps)
Action Executor
    ↓ (verify)
UI Twin + Vision
    ↓ (store memory)
RAG Retriever
```

## Key Features

### Native Layer
- **Real-time capture**: 30-60 FPS screen streaming
- **Event streaming**: Accessibility events in real-time
- **Low latency**: < 50ms from event to service
- **Platform-native**: Swift (macOS), C# (Windows)

### UI Twin
- **Element graph**: Real-time in-memory UI state
- **Temporal buffer**: Last 200 UI snapshots
- **Fast lookup**: Find elements by role, text, window
- **Auto-cleanup**: Remove stale elements after 5 minutes

### Action Executor
- **Safe execution**: Validation and confirmation
- **Verification**: Post-action verification
- **Screenshots**: Before/after capture
- **Platform support**: macOS and Windows

### Vision
- **OCR**: Text extraction with Tesseract
- **VLM**: Screen description with GPT-4V/Claude
- **Fast**: ~100ms OCR, ~1-3s VLM

### RAG Retriever
- **Vector search**: Semantic similarity with embeddings
- **Namespaces**: Organize by type (docs, past runs)
- **Persistent**: ChromaDB storage
- **Fast**: ~50-100ms retrieval

### Planner
- **RAG-enhanced**: Context from docs + past runs
- **LLM planning**: GPT-4 generates step-by-step plans
- **Replanning**: Recovers from failures
- **Episodic memory**: Stores execution history
- **LangGraph**: State machine orchestration

## Security & Safety

### Permissions
- Screen Recording and Accessibility prompts on first run
- Clear permission descriptions in Info.plist

### Safety Constraints
- Two-step confirmation for destructive operations
- Timeout for all actions (default 5s)
- Failsafe: move mouse to corner to abort (PyAutoGUI)

### Privacy
- Local-first: all processing on-device by default
- Optional cloud: only for VLM features
- On-screen LED: shows when system is active (to be implemented)

### Audit
- All actions logged
- Episodic memory of executions
- Screenshot capture for verification

## Production Deployment

### Single Machine
```bash
# Use process manager (e.g., supervisord, systemd)
supervisorctl start capture_service
supervisorctl start accessibility_bridge
supervisorctl start ui_twin
supervisorctl start action_executor
supervisorctl start vision
supervisorctl start rag_retriever
supervisorctl start planner
```

### Multi-Machine
- Run native services on user's machine
- Host Python services on server(s)
- Use Redis for pub/sub between services
- Load balance multiple executor workers

### Cloud
- Vision service: GPU server for VLM
- RAG Retriever: Managed vector DB (Pinecone, Qdrant)
- Planner: Kubernetes for scaling

## Development

### Adding a New Action Type

1. Update `services/action_executor/models.py`:
```python
class ActionType(str, Enum):
    # ... existing ...
    DOUBLE_CLICK = "double_click"
```

2. Update platform executors (`macos.py`, `windows.py`):
```python
async def _double_click(self, action: Action, element):
    # Implementation
```

### Adding a New RAG Namespace

```python
# Index documents
docs = load_documents("python_docs/")
for doc in docs:
    await rag_service.index(Document(
        id=doc.id,
        content=doc.content,
        namespace="python_docs",
        metadata=doc.metadata
    ))
```

### Extending Vision Service

```python
# Add custom vision model
class CustomVisionService(VisionService):
    async def _run_custom_detection(self, image):
        # Your detection logic
        return detected_objects
```

## Troubleshooting

### CaptureService not capturing
- Check Screen Recording permission
- Try `CGPreflightScreenCaptureAccess()` in terminal
- Restart app after granting permission

### AccessibilityBridge not receiving events
- Check Accessibility permission
- Restart app after granting permission
- Check Console.app for errors

### Action Executor not clicking
- Check element selector accuracy
- Verify UI Twin has the element
- Check coordinates are on-screen

### Vision service OCR not working
- Install Tesseract: `brew install tesseract`
- Check image quality (needs ~200 DPI)

### RAG retrieval returning no results
- Check namespace exists
- Verify documents were indexed
- Lower `min_score` threshold

### Planner timing out
- Increase `timeout_seconds` in task
- Check LLM API availability
- Verify all services are running

## Testing

### Unit Tests
```bash
# Each service
cd services/ui_twin
pytest tests/

cd services/action_executor
pytest tests/
```

### Integration Tests
```bash
# Full system test
python tests/integration/test_full_workflow.py
```

### Manual Testing
```bash
# Test native services
curl http://localhost:8765  # Should connect

# Test Python services
curl http://localhost:8080/health  # Action Executor
curl http://localhost:8081/health  # Vision
curl http://localhost:8082/health  # RAG
curl http://localhost:8083/health  # Planner
```

## Performance Benchmarks

| Component           | Latency  | Throughput |
|---------------------|----------|------------|
| Screen capture      | < 33ms   | 30 FPS     |
| Accessibility event | < 10ms   | Real-time  |
| UI Twin lookup      | < 5ms    | 1000/s     |
| Action execution    | 100-500ms| Varies     |
| OCR                 | 100-300ms| 3-10/s     |
| VLM                 | 1-3s     | 0.3-1/s    |
| RAG retrieval       | 50-100ms | 10-20/s    |
| Planning            | 1-3s     | 0.3-1/s    |

## Roadmap

### Phase 1 (Current)
- ✅ Native capture services (macOS)
- ✅ Python orchestration services
- ✅ Basic action execution
- ✅ RAG retrieval

### Phase 2 (Next)
- [ ] Windows native services (complete implementation)
- [ ] Advanced vision (object detection, UI element detection)
- [ ] Multi-step task templates
- [ ] UI for monitoring

### Phase 3 (Future)
- [ ] Multi-agent collaboration
- [ ] Learning from demonstrations
- [ ] Custom action recording
- [ ] Browser automation integration

## License

Part of the Shail AI system.

## Support

For issues and questions:
1. Check service logs
2. Verify all services are running
3. Test individual components
4. Check permissions (macOS)

## Contributing

1. Each service is independent
2. Add tests for new features
3. Update READMEs
4. Follow existing code style

