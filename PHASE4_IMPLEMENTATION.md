# Phase 4: Backend WebSocket & LangGraph State - Implementation Complete

## Overview
Phase 4 implements real-time state synchronization between the Python backend (LangGraph) and Swift UI via WebSocket. This enables the UI to visualize the planner's execution flow in real-time.

## ✅ Completed Components

### 1. Backend WebSocket Server
**File**: `apps/shail/websocket_server.py`

- ✅ `BrainWebSocketManager` class for connection management
- ✅ State broadcasting to all connected clients
- ✅ State history (last 100 states) for new connections
- ✅ Event broadcasting for custom events
- ✅ Ping/pong support for connection keepalive
- ✅ Proper error handling and disconnection management
- ✅ Fixed timestamp to use `time.time()` instead of `asyncio.get_event_loop().time()`

**Key Features:**
- Manages multiple WebSocket connections
- Maintains state history for late-joining clients
- Handles disconnections gracefully
- Broadcasts both state updates and custom events

### 2. WebSocket Endpoint
**File**: `apps/shail/main.py` (MODIFIED)

- ✅ `/ws/brain` endpoint registered
- ✅ Handles client connections/disconnections
- ✅ Message handling (ping, subscribe)
- ✅ Integrated with FastAPI app

### 3. LangGraph State Serialization
**File**: `services/planner/graph.py` (MODIFIED)

- ✅ `serialize_graph_state()` function
- ✅ Converts LangGraph state to JSON-serializable format
- ✅ Extracts nodes and edges from graph structure
- ✅ Determines current node based on state
- ✅ Includes metadata (status, errors, steps)
- ✅ **FIXED**: Now extracts actual graph edges instead of returning empty array
- ✅ Falls back to known graph structure if extraction fails

**Edge Extraction:**
- Attempts to extract edges from LangGraph structure
- Falls back to known planner graph edges if extraction fails
- Includes conditional edges (continue, error, complete)

### 4. Planner Service Integration
**File**: `services/planner/service.py` (MODIFIED)

- ✅ `_broadcast_state()` method
- ✅ Broadcasts state at all key execution points:
  - Plan creation (`planning`)
  - Plan execution start (`executing`)
  - Step execution (`executing_step`)
  - Step completion (`step_completed`)
  - Replanning (`replanning`)
  - Completion (`completed`)
  - Failure (`failed`)
- ✅ **FIXED**: WebSocket manager import with multiple fallback paths
- ✅ **FIXED**: State broadcast on plan creation (was missing)
- ✅ Graceful fallback if WebSocket manager unavailable

**Import Path Fix:**
- Tries multiple import paths: `apps.shail.websocket_server`, `shail.websocket_server`, `websocket_server`
- Works in both standalone and integrated modes
- Logs connection status for debugging

### 5. Swift WebSocket Client
**File**: `apps/mac/ShailUI/BackendWebSocketClient.swift`

- ✅ `BackendWebSocketClient` class
- ✅ Connects to `ws://localhost:8000/ws/brain`
- ✅ Receives state updates and state history
- ✅ Auto-reconnection with exponential backoff
- ✅ Ping/pong keepalive (every 30 seconds)
- ✅ `GraphState` and `PlanStep` models
- ✅ **ENHANCED**: Added `GraphEdge` model for edge visualization
- ✅ Parses edges from state updates

**Models:**
- `GraphState`: Complete state with nodes, edges, plan steps, metadata
- `PlanStep`: Individual plan step with execution status
- `GraphEdge`: Graph edge with from/to nodes and optional condition

### 6. BirdsEyeView Integration
**File**: `apps/mac/ShailUI/BirdsEyeView.swift` (MODIFIED)

- ✅ Uses `BackendWebSocketClient`
- ✅ Displays real-time LangGraph state
- ✅ Shows connection status indicator
- ✅ Renders nodes dynamically from state
- ✅ **ENHANCED**: Renders edges from graph state
- ✅ Shows plan steps in sidebar
- ✅ Visual status indicators (active/completed/failed)
- ✅ Updates automatically on state changes

**Edge Rendering:**
- Uses edges from state if available
- Falls back to sequential node connections
- Visual distinction for different edge types

## Architecture Flow

```
Planner Service
    ↓
_broadcast_state()
    ↓
serialize_graph_state()
    ↓
websocket_manager.broadcast_state()
    ↓
WebSocket Clients (/ws/brain)
    ↓
BackendWebSocketClient (Swift)
    ↓
BirdsEyeView (UI Update)
```

## Files Created/Modified

### New Files:
1. `apps/shail/websocket_server.py` - WebSocket server and manager
2. `apps/mac/ShailUI/BackendWebSocketClient.swift` - Swift WebSocket client

### Modified Files:
1. `apps/shail/main.py` - Added `/ws/brain` endpoint
2. `services/planner/graph.py` - Added `serialize_graph_state()` with edge extraction
3. `services/planner/service.py` - Added `_broadcast_state()` and integration
4. `apps/mac/ShailUI/BirdsEyeView.swift` - Integrated WebSocket client and edge rendering
5. `apps/mac/ShailUI/Package.swift` - Added BackendWebSocketClient.swift

## WebSocket Protocol

### Client → Server Messages

**Ping:**
```json
{"type": "ping"}
```

**Subscribe:**
```json
{"type": "subscribe"}
```

### Server → Client Messages

**State Update:**
```json
{
  "type": "state_update",
  "timestamp": 1234567890.123,
  "state": {
    "task_description": "task-123",
    "current_step": 2,
    "status": "executing",
    "current_node": "execute_step",
    "nodes": ["retrieve_context", "generate_plan", "execute_step", "verify_step", "replan", "finalize"],
    "edges": [
      {"from": "retrieve_context", "to": "generate_plan"},
      {"from": "generate_plan", "to": "execute_step"},
      {"from": "execute_step", "to": "verify_step"},
      {"from": "verify_step", "to": "execute_step", "condition": "continue"},
      {"from": "verify_step", "to": "replan", "condition": "error"},
      {"from": "verify_step", "to": "finalize", "condition": "complete"},
      {"from": "replan", "to": "execute_step"},
      {"from": "finalize", "to": "END"}
    ],
    "plan_steps": [
      {
        "step_id": "step_1",
        "description": "Open terminal",
        "step_type": "action",
        "executed": true,
        "success": true,
        "error": null
      }
    ],
    "plan_id": "plan_123",
    "task_id": "task-123",
    "step_count": 5,
    "current_step_index": 2,
    "metadata": {
      "has_error": false,
      "step_count": 5,
      "completed_steps": 2,
      "has_context": true
    }
  }
}
```

**State History:**
```json
{
  "type": "state_history",
  "states": [...]
}
```

**Event:**
```json
{
  "type": "event",
  "event_type": "node_started",
  "timestamp": 1234567890.123,
  "data": {...}
}
```

## Bugs Fixed

### 1. WebSocket Manager Import Path
**Issue**: Import failed when Planner service ran standalone
**Fix**: Added multiple import path fallbacks with proper error handling

### 2. Missing State Broadcast on Plan Creation
**Issue**: State not broadcast when plan was created
**Fix**: Added `_broadcast_state(plan, "planning")` after plan creation

### 3. Empty Edges Array
**Issue**: `serialize_graph_state()` returned empty edges array
**Fix**: Implemented edge extraction from LangGraph structure with fallback to known edges

### 4. Timestamp Inconsistency
**Issue**: Used `asyncio.get_event_loop().time()` which is relative
**Fix**: Changed to `time.time()` for absolute timestamps

### 5. Indentation Error in create_plan
**Issue**: Code after try block was not properly indented
**Fix**: Fixed indentation to ensure proper exception handling

## Usage

### Backend (Python)
The Planner service automatically broadcasts state when executing plans. No additional code needed.

**Example:**
```python
# State is automatically broadcast during:
# - Plan creation
# - Plan execution
# - Step execution
# - Step completion
# - Replanning
# - Completion/failure
```

### Frontend (Swift)
```swift
@StateObject private var wsClient = BackendWebSocketClient()

// In view
.onAppear {
    wsClient.connect()
}

// Access state
if let state = wsClient.currentState {
    // Use state.currentNode, state.nodes, state.edges, state.planSteps, etc.
}
```

## Testing

### 1. Start Backend:
```bash
cd apps/shail
python main.py
```

### 2. Start Planner Service:
```bash
cd services/planner
python service.py
```

### 3. Create a Plan:
```bash
curl -X POST http://localhost:8083/plan \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-1",
    "description": "Test task"
  }'
```

### 4. Connect Swift UI:
- Launch ShailUI app
- Navigate to Bird's Eye view
- Should see:
  - Connection status (green = connected)
  - Real-time state updates
  - Graph nodes and edges
  - Plan steps in sidebar

### 5. Execute Plan:
```bash
curl -X POST http://localhost:8083/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-1",
    "description": "Test task"
  }'
```

**Expected Behavior:**
- UI should show state updates in real-time
- Nodes should highlight as execution progresses
- Edges should be visible between nodes
- Plan steps should update with execution status

## Known Limitations

1. **Graph Structure**: Edge extraction may not work for all LangGraph configurations. Falls back to known structure.

2. **State History**: Limited to last 100 states. May need adjustment based on use case.

3. **Connection Recovery**: Auto-reconnection works but may miss state updates during disconnection.

4. **Performance**: Broadcasting to many clients simultaneously may impact performance. Consider rate limiting if needed.

## Next Steps

Phase 4 is **COMPLETE**! All components are implemented, tested, and bugs fixed.

Ready to proceed with:
- **Phase 5**: Bird's Eye Graph Visualization (enhancements)
- **Phase 6**: Chat & Detail View Integration
- **Phase 7+**: Additional features and optimizations

## Troubleshooting

### WebSocket Not Connecting
- Verify backend is running on port 8000
- Check WebSocket URL in `BackendWebSocketClient` (default: `ws://localhost:8000/ws/brain`)
- Check console logs for connection errors

### No State Updates
- Verify Planner service is connected to WebSocket manager (check logs)
- Ensure plan execution is happening
- Check WebSocket connection status in UI

### Missing Edges
- Edges are extracted from LangGraph structure
- If extraction fails, falls back to known structure
- Check `serialize_graph_state()` logs for edge extraction status

### Import Errors
- WebSocket manager import tries multiple paths
- Check logs for which import path succeeded
- If all fail, state broadcasting is disabled (graceful degradation)

