# Action Executor Service

Safe UI action execution with verification and safety constraints.

## Features

- **HTTP/JSON API**: RESTful API for action execution
- **Safety Checks**: Validation and confirmation for destructive operations
- **Verification**: Post-execution verification of action success
- **Screenshots**: Capture before/after screenshots
- **Platform Support**: macOS and Windows via PyAutoGUI + native APIs

## API Endpoints

### POST /action/click
Execute a click action.

```json
{
  "action_id": "click-123",
  "element_selector": {
    "role": "AXButton",
    "text": "Submit"
  },
  "confirm": false,
  "timeout_ms": 5000,
  "screenshot_after": true
}
```

Response:
```json
{
  "action_id": "click-123",
  "status": "success",
  "result": "click action completed successfully",
  "duration_ms": 245.6,
  "verified": true,
  "screenshot_after_id": "screenshot_1234567890"
}
```

### POST /action/type
Type text into focused element.

```json
{
  "action_id": "type-456",
  "text": "Hello, World!",
  "timeout_ms": 3000
}
```

### POST /action/press_key
Press a keyboard key.

```json
{
  "action_id": "key-789",
  "key": "enter"
}
```

### GET /health
Health check endpoint.

## Running the Service

```bash
cd services/action_executor
pip install -r requirements.txt
python service.py
```

The API will be available at `http://localhost:8080`.

## Integration

### With UI Twin
The Action Executor can resolve elements using the UI Twin service:

```python
from services.ui_twin import UITwinService
from services.action_executor import ActionExecutorService

ui_twin = UITwinService()
executor = ActionExecutorService(ui_twin=ui_twin)

# Now actions can use element_selector instead of coordinates
```

### With Planner
The Planner service calls the Action Executor API:

```python
import httpx

async def execute_plan_step(step):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8080/action/click",
            json=step.to_action_dict()
        )
        return response.json()
```

## Safety Features

- **Confirmation**: Require user confirmation for destructive actions
- **Timeout**: Automatic timeout if action takes too long
- **Verification**: Check that action had desired effect
- **Failsafe**: Move mouse to corner to abort (PyAutoGUI feature)

## Platform-Specific Notes

### macOS
- Uses PyAutoGUI for basic actions
- Can integrate with AppleScript for advanced automation
- Requires Accessibility permissions

### Windows
- Uses PyAutoGUI for basic actions
- Can integrate with UI Automation API
- No special permissions required

## License

Part of the Shail AI system.

