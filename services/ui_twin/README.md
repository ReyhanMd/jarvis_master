# UI Twin Service

Real-time digital twin of the UI state, consuming accessibility events and screen frames.

## Features

- **Element Graph**: In-memory graph of all UI elements with real-time updates
- **Temporal Buffer**: Ring buffer of last N UI snapshots for time-travel queries
- **Element Lookup**: Find elements by role, text, title, window, app name
- **State Serialization**: Export current UI state as JSON
- **Auto-Cleanup**: Remove stale elements after 5 minutes

## Architecture

```
AccessibilityBridge (ws://localhost:8766)
         │
         ├─> UITwinService
         │        │
CaptureService (ws://localhost:8765) ─┘
                 │
                 └─> Element Graph + Temporal Buffer
```

## Usage

### Running the Service

```bash
cd services/ui_twin
pip install -r requirements.txt
python service.py
```

### Programmatic Usage

```python
from services.ui_twin import UITwinService, ElementSelector

service = UITwinService()
await service.start()

# Find element
selector = ElementSelector(role="AXButton", text="Submit")
element = service.get_element_by_selector(selector)

print(f"Element: {element.text} at {element.bbox}")

# Get all elements in a window
selector = ElementSelector(window="Safari")
elements = service.get_elements_by_selector(selector)

# Serialize state
json_state = service.serialize()
```

## Data Models

### UIElement
- `id`: Unique identifier
- `role`: UI role (button, textfield, etc)
- `text`: Element text content
- `title`: Element title/label
- `bbox`: Bounding box (x1, y1, x2, y2)
- `window`: Parent window name
- `app_name`: Application name
- `last_seen`: Last update timestamp
- `meta`: Additional metadata

### UISnapshot
- `timestamp`: Snapshot time
- `delta`: Changed elements or events
- `snapshot_type`: full, delta, or event

## Integration with Other Services

### Vision Service
Screen frames are forwarded to the vision service for OCR and visual analysis.

### Action Executor
Provides element lookup for action execution (e.g., "click button named 'Submit'").

### Planner
Provides current UI state context for planning decisions.

## License

Part of the Shail AI system.

