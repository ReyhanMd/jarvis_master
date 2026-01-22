# LangGraph Integration - Quick Start

## ✅ Setup Complete!

All code has been implemented. To use it:

### 1. Install Dependencies

```bash
# Run the setup script
./setup_langgraph.sh

# Or manually:
pip install -r requirements.txt
pip install langgraph>=0.2.0 langgraph-checkpoint>=0.2.0
```

### 2. Configure API Keys

Create `.env` file in project root:

```bash
# Required
GEMINI_API_KEY=your_key_here
KIMI_K2_API_KEY=your_key_here

# Optional (for ChatGPT worker)
OPENAI_API_KEY=your_key_here

# Optional (for LangGraph Cloud)
LANGGRAPH_CLOUD_API_KEY=your_key_here
USE_LANGGRAPH_CLOUD=false
```

### 3. Verify Installation

```bash
python3 -c "from shail.orchestration.langgraph_integration import get_state_graph; print('✅ Working!' if get_state_graph() else '❌ Failed')"
```

### 4. Run Tests

```bash
python3 -m pytest tests/test_langgraph_integration.py -v
```

### 5. Start Shail

```bash
# Start the service
./start_shail.sh

# Or manually:
python3 -m uvicorn apps.shail.main:app --reload
```

### 6. Test Streaming

Connect to WebSocket: `ws://localhost:8000/ws/brain`

You should see incremental `node_update` events as tasks execute.

## Features Implemented

✅ Multi-agent orchestration with LangGraph
✅ Real-time streaming via WebSocket
✅ Checkpointing (memory + SQLite)
✅ Error recovery with retry
✅ LangGraph Studio integration
✅ Production-grade monitoring
✅ Rate limiting and throttling

## Documentation

- Full details: `docs/LANGGRAPH_INTEGRATION.md`
- Setup guide: `docs/LANGGRAPH_SETUP_COMPLETE.md`

## Troubleshooting

**Import errors?**
- Run: `pip install langgraph langgraph-checkpoint`
- Check: `python3 -c "import langgraph; print(langgraph.__file__)"`

**Streaming not working?**
- Check WebSocket connection
- Verify `brain_ws_manager` is initialized
- Check logs for errors

**Tests failing?**
- Install pytest: `pip install pytest pytest-asyncio`
- Check API keys are set
- Verify LangGraph is installed
