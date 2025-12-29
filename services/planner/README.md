# Planner Service

LangGraph-based task orchestration service that plans and executes complex tasks.

## Features

- **RAG-Enhanced Planning**: Retrieves docs and past runs for context
- **LLM-Based Planning**: Generates step-by-step execution plans
- **Action Execution**: Coordinates with Action Executor service
- **Verification**: Checks action results via UI Twin and Vision
- **Replanning**: Recovers from failures by generating new plans
- **Episodic Memory**: Stores execution history for future reference
- **LangGraph Workflow**: State machine for complex orchestration

## Architecture

```
User Task
    ↓
RAG Retrieval (context)
    ↓
LLM Planning (generate steps)
    ↓
Execute Step → Verify → Next Step
    ↓ (failure)
Replan → Execute
    ↓ (success)
Store Episodic Memory
    ↓
Return Result
```

## Running the Service

```bash
cd services/planner
pip install -r requirements.txt

# Set API keys
export OPENAI_API_KEY=your-key

python service.py
```

The API will be available at `http://localhost:8083`.

## API Endpoints

### POST /plan
Create execution plan without executing.

```json
{
  "task_id": "task-123",
  "description": "Create a git commit with message 'initial commit'",
  "context": {},
  "constraints": ["don't push to remote"],
  "timeout_seconds": 300
}
```

Response:
```json
{
  "plan_id": "plan_1234567890",
  "task_id": "task-123",
  "status": "pending",
  "steps": [
    {
      "step_id": "step_1",
      "step_type": "action",
      "description": "Open terminal",
      "action": {"type": "click", "element_selector": {"role": "AXButton", "text": "Terminal"}}
    },
    {
      "step_id": "step_2",
      "step_type": "action",
      "description": "Type git command",
      "action": {"type": "type", "text": "git commit -m 'initial commit'"}
    }
  ],
  "retrieved_context": ["[Documentation] git commit creates a new commit..."]
}
```

### POST /execute
Plan and execute task.

```json
{
  "task_id": "task-123",
  "description": "Create a git commit with message 'initial commit'"
}
```

Response includes execution results for each step.

### GET /plan/{plan_id}
Get plan status and results.

## Integration Example

```python
import httpx

async def execute_task(description: str):
    async with httpx.AsyncClient() as client:
        # Execute task
        response = await client.post(
            "http://localhost:8083/execute",
            json={
                "task_id": f"task_{int(time.time())}",
                "description": description
            },
            timeout=300.0
        )
        
        plan = response.json()
        
        if plan["success"]:
            print(f"✅ Task completed: {plan['result_summary']}")
        else:
            print(f"❌ Task failed: {plan['result_summary']}")
        
        return plan

# Use it
plan = await execute_task("Create a new Python file named test.py")
```

## LangGraph Workflow

The planner uses a state machine:

```python
# States
class PlannerState:
    task_description: str
    context: list[str]
    plan_steps: list[dict]
    current_step: int
    execution_results: list[dict]
    status: str
    error: str | None

# Nodes (functions that process state)
- retrieve_context: Get RAG context
- generate_plan: Create steps using LLM
- execute_step: Run action via executor
- verify_step: Check result
- replan: Generate recovery plan on failure
- finalize: Complete execution

# Edges (transitions)
retrieve_context → generate_plan → execute_step → verify_step
                                         ↓ (success)    ↓ (failure)
                                    next step      replan
```

## Replanning on Failure

When a step fails, the planner:

1. Retrieves error context
2. Gets similar failures from past runs (RAG)
3. Asks LLM to generate recovery plan
4. Executes recovery plan
5. Continues with original plan

Example:
```
Original Plan:
1. Click "Submit" button

Failure: Button not found

Recovery Plan:
1. Wait 1 second for UI to load
2. Take screenshot
3. Use vision service to locate button
4. Click button at coordinates

Continue with original plan...
```

## Service Dependencies

- **RAG Retriever** (port 8082): Context retrieval
- **Action Executor** (port 8080): Action execution
- **UI Twin** (port 8080): Element lookup
- **Vision** (port 8081): Visual verification

## Performance

- Planning: ~1-3s (includes RAG retrieval + LLM)
- Step execution: ~500ms - 5s per step
- Total: Depends on plan complexity

## License

Part of the Shail AI system.

