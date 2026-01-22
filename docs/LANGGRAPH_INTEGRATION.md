# LangGraph Integration (Shail)

## What changed
- Cloned LangGraph source into `langgraph/`.
- Added centralized import helper `shail/orchestration/langgraph_integration.py`.
- Added checkpointing (`shail/orchestration/checkpointing.py`) with memory primary and SQLite backup.
- Implemented orchestration nodes (master, workers, permission, recovery).
- Completed `LangGraphExecutor` with checkpoints, metrics, and WebSocket broadcast.
- Enhanced planner graph state schema and checkpointing.
- Added `langgraph.json` for Studio (local + cloud hooks).

## How to run
1. Ensure virtualenv active and dependencies installed:
   ```bash
   pip install -r requirements.txt
   ```
2. Start Shail FastAPI app (planner and orchestration use LangGraph automatically).
3. For Studio (local):
   ```bash
   LANGGRAPH_ENV=local python -m langgraph_cli dev
   ```
4. For Cloud: set `LANGGRAPH_API_KEY` and `LANGGRAPH_PROJECT` (see `langgraph.json`).

## Key entry points
- Orchestration graph: `shail/orchestration/graph.py` (`LangGraphExecutor`).
- Planner graph: `services/planner/graph.py`.
- Nodes catalog: `shail/orchestration/nodes/`.
- Studio config: `langgraph.json`.

## Testing
```bash
pytest tests/test_langgraph_integration.py
```

## Notes
- WebSocket streaming uses `apps/shail/websocket_server.py`.
- Rate limiting added in `shail/core/router.py`.
- Checkpoints default to `shail_memory.sqlite3`; override via settings if needed.
