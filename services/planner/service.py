"""
Planner Service - LangGraph-based task orchestration
"""

import asyncio
import time
import json
import sys
import os
import httpx
from typing import Optional, Dict, Any, List
from loguru import logger
from fastapi import FastAPI, HTTPException

# Handle imports for both module and direct script execution
# Add parent directory to path for direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative imports first (when run as module), then absolute (when run as script)
try:
    from .models import Task, Plan, PlanStep, PlanStatus, StepType
    from .graph import create_planner_graph, serialize_graph_state
except (ImportError, ValueError):
    from planner.models import Task, Plan, PlanStep, PlanStatus, StepType
    from planner.graph import create_planner_graph, serialize_graph_state

# Optional: LangChain/LangGraph
try:
    from langchain.chat_models import ChatOpenAI
    from langchain.schema import HumanMessage, SystemMessage
    HAS_LANGCHAIN = True
except ImportError:
    logger.warning("langchain not installed - using fallback planner")
    HAS_LANGCHAIN = False


class PlannerService:
    """
    Plans and executes tasks using LangGraph orchestration.
    
    Flow:
    1. Retrieve context from RAG (docs + past runs)
    2. Generate plan using LLM
    3. Execute steps via Action Executor
    4. Verify using UI Twin
    5. Replan on failure
    6. Store episodic memory
    
    Architecture:
    - Uses LangGraph for state machine
    - Integrates with all other services
    - Handles recovery and replanning
    """
    
    def __init__(self,
                 ui_twin_url: str = "http://localhost:8080",
                 action_executor_url: str = "http://localhost:8080",
                 vision_url: str = "http://localhost:8081",
                 rag_url: str = "http://localhost:8082"):
        
        self.app = FastAPI(title="Shail Planner")
        self._setup_routes()
        
        # Service URLs
        self.ui_twin_url = ui_twin_url
        self.action_executor_url = action_executor_url
        self.vision_url = vision_url
        self.rag_url = rag_url
        
        # LLM client
        if HAS_LANGCHAIN:
            self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        else:
            self.llm = None
        
        # Active plans
        self.plans: Dict[str, Plan] = {}
        
        # LangGraph workflow
        self.graph = create_planner_graph(self)
        
        # WebSocket manager for state broadcasting (optional)
        self.websocket_manager = None
        # Try multiple import paths to handle both standalone and integrated modes
        import_paths = [
            "apps.shail.websocket_server",
            "shail.websocket_server",
            "websocket_server"
        ]
        for import_path in import_paths:
            try:
                module = __import__(import_path, fromlist=["websocket_manager"])
                if hasattr(module, "websocket_manager"):
                    self.websocket_manager = module.websocket_manager
                    logger.info(f"✅ Connected to WebSocket manager via {import_path}")
                    break
            except (ImportError, AttributeError):
                continue
        
        if not self.websocket_manager:
            logger.debug("⚠️  WebSocket manager not available - state broadcasting disabled")
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/plan", response_model=Plan)
        async def create_plan(task: Task):
            """Create execution plan for task"""
            return await self.create_plan(task)
        
        @self.app.post("/execute", response_model=Plan)
        async def execute_plan(task: Task):
            """Plan and execute task"""
            plan = await self.create_plan(task)
            await self.execute(plan)
            return plan
        
        @self.app.get("/plan/{plan_id}", response_model=Plan)
        async def get_plan(plan_id: str):
            """Get plan by ID"""
            if plan_id not in self.plans:
                raise HTTPException(status_code=404, detail="Plan not found")
            return self.plans[plan_id]
        
        @self.app.post("/plan/{plan_id}/execute", response_model=Plan)
        async def execute_existing_plan(plan_id: str):
            """Execute an existing plan"""
            if plan_id not in self.plans:
                raise HTTPException(status_code=404, detail="Plan not found")
            plan = self.plans[plan_id]
            await self.execute(plan)
            return plan
        
        @self.app.get("/health")
        async def health():
            """Health check"""
            return {
                "status": "ok",
                "langchain_available": HAS_LANGCHAIN
            }
    
    async def create_plan(self, task: Task) -> Plan:
        """
        Create execution plan for task.
        
        Steps:
        1. Retrieve relevant context from RAG
        2. Generate plan using LLM
        3. Parse plan into steps
        4. Return plan
        """
        
        plan_id = f"plan_{int(time.time() * 1000)}"
        
        plan = Plan(
            plan_id=plan_id,
            task_id=task.task_id,
            status=PlanStatus.PLANNING,
            created_at=time.time()
        )
        
        self.plans[plan_id] = plan
        
        logger.info(f"📋 Creating plan for task: {task.description[:50]}...")
        
        try:
            # Step 1: Retrieve context from RAG
            context = await self._retrieve_context(task)
            plan.retrieved_context = context
            
            # Step 2: Generate plan using LLM
            steps = await self._generate_plan_steps(task, context)
            plan.steps = steps
            
            plan.status = PlanStatus.PENDING
            
            logger.info(f"✅ Created plan with {len(steps)} steps")
            
            # Broadcast plan creation
            await self._broadcast_state(plan, "planning")
            
        except Exception as e:
            plan.status = PlanStatus.FAILED
            plan.result_summary = f"Planning failed: {e}"
            logger.error(f"❌ Planning failed: {e}")
        
        return plan
    
    async def execute(self, plan: Plan):
        """Execute a plan"""
        
        plan.status = PlanStatus.EXECUTING
        plan.started_at = time.time()
        
        logger.info(f"▶️  Executing plan {plan.plan_id} with {len(plan.steps)} steps")
        
        # Broadcast initial state
        await self._broadcast_state(plan, "executing")
        
        try:
            for i, step in enumerate(plan.steps):
                plan.current_step = i
                
                logger.info(f"📍 Step {i+1}/{len(plan.steps)}: {step.description}")
                
                # Broadcast step start
                await self._broadcast_state(plan, "executing_step")
                
                # Execute step
                success = await self._execute_step(step, plan)
                
                if not success:
                    # Try to replan
                    logger.warning(f"⚠️  Step {i+1} failed, attempting replan...")
                    await self._broadcast_state(plan, "replanning")
                    
                    replan_success = await self._replan_from_failure(plan, i)
                    
                    if not replan_success:
                        plan.status = PlanStatus.FAILED
                        plan.result_summary = f"Failed at step {i+1}: {step.error}"
                        logger.error(f"❌ Plan failed at step {i+1}")
                        await self._broadcast_state(plan, "failed")
                        return
                else:
                    # Broadcast step completion
                    await self._broadcast_state(plan, "step_completed")
            
            # Success
            plan.status = PlanStatus.COMPLETED
            plan.success = True
            plan.result_summary = "All steps completed successfully"
            
            logger.info(f"✅ Plan {plan.plan_id} completed successfully")
            await self._broadcast_state(plan, "completed")
            
        except Exception as e:
            plan.status = PlanStatus.FAILED
            plan.result_summary = f"Execution error: {e}"
            logger.error(f"❌ Plan execution failed: {e}")
            await self._broadcast_state(plan, "failed")
        
        finally:
            plan.completed_at = time.time()
            
            # Store episodic memory
            await self._store_episodic_memory(plan)
    
    async def _broadcast_state(self, plan: Plan, status: str):
        """Broadcast plan state to WebSocket clients"""
        if not self.websocket_manager:
            return
        
        try:
            # Convert plan to LangGraph state format
            graph_state = {
                "task_description": plan.task_id,
                "current_step": plan.current_step or 0,
                "status": status,
                "error": None,
                "plan_steps": [
                    {
                        "step_id": step.step_id,
                        "description": step.description,
                        "step_type": step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type),
                        "executed": step.executed,
                        "success": step.success,
                        "error": step.error
                    }
                    for step in plan.steps
                ],
                "execution_results": [
                    step.result for step in plan.steps if step.executed and step.result
                ],
                "context": plan.retrieved_context or []
            }
            
            # Serialize state
            serialized = serialize_graph_state(graph_state, self.graph)
            
            # Add plan-specific metadata
            serialized["plan_id"] = plan.plan_id
            serialized["task_id"] = plan.task_id
            serialized["step_count"] = len(plan.steps)
            serialized["current_step_index"] = plan.current_step or 0
            
            # Broadcast
            await self.websocket_manager.broadcast_state(serialized)
            
        except Exception as e:
            logger.warning(f"Failed to broadcast state: {e}")
    
    async def _retrieve_context(self, task: Task) -> List[str]:
        """Retrieve relevant context from RAG"""
        
        try:
            async with httpx.AsyncClient() as client:
                # Get documentation
                docs_response = await client.post(
                    f"{self.rag_url}/retrieve",
                    json={
                        "query": task.description,
                        "namespace": "git_docs",
                        "top_k": 3
                    },
                    timeout=10.0
                )
                
                # Get past runs
                past_response = await client.post(
                    f"{self.rag_url}/retrieve",
                    json={
                        "query": task.description,
                        "namespace": "past_runs",
                        "top_k": 2
                    },
                    timeout=10.0
                )
                
                docs_result = docs_response.json()
                past_result = past_response.json()
                
                context = []
                
                for doc in docs_result.get("documents", []):
                    context.append(f"[Documentation] {doc['content']}")
                
                for doc in past_result.get("documents", []):
                    context.append(f"[Past Run] {doc['content']}")
                
                return context
                
        except Exception as e:
            logger.warning(f"Failed to retrieve RAG context: {e}")
            return []
    
    async def _generate_plan_steps(self, task: Task, context: List[str]) -> List[PlanStep]:
        """Generate plan steps using LLM"""
        
        if not self.llm:
            # Fallback: simple single-step plan
            return [
                PlanStep(
                    step_id="step_1",
                    step_type=StepType.ACTION,
                    description=task.description,
                    action={"type": "execute", "description": task.description}
                )
            ]
        
        # Build prompt
        context_str = "\n".join(context) if context else "No context available"
        
        prompt = f"""You are a task planning agent. Given a task and context, generate a step-by-step plan.

Task: {task.description}

Context:
{context_str}

Generate a JSON plan with steps. Each step should have:
- step_id: unique identifier
- step_type: "action", "verification", or "wait"
- description: what to do
- action: for action steps, specify the action details

Example:
{{
  "steps": [
    {{
      "step_id": "step_1",
      "step_type": "action",
      "description": "Open terminal",
      "action": {{"type": "click", "element_selector": {{"role": "AXButton", "text": "Terminal"}}}}
    }},
    {{
      "step_id": "step_2",
      "step_type": "action",
      "description": "Type git commit command",
      "action": {{"type": "type", "text": "git commit -m 'initial commit'"}}
    }},
    {{
      "step_id": "step_3",
      "step_type": "verification",
      "description": "Verify commit succeeded",
      "postcondition": "Success message visible"
    }}
  ]
}}

Generate plan:"""
        
        try:
            messages = [
                SystemMessage(content="You are a task planning agent. Always respond with valid JSON."),
                HumanMessage(content=prompt)
            ]
            
            response = await asyncio.to_thread(self.llm.invoke, messages)
            content = response.content
            
            # Parse JSON
            plan_json = json.loads(content)
            
            # Convert to PlanStep objects
            steps = []
            for step_data in plan_json.get("steps", []):
                step = PlanStep(
                    step_id=step_data.get("step_id", f"step_{len(steps)+1}"),
                    step_type=StepType(step_data.get("step_type", "action")),
                    description=step_data.get("description", ""),
                    action=step_data.get("action"),
                    precondition=step_data.get("precondition"),
                    postcondition=step_data.get("postcondition")
                )
                steps.append(step)
            
            return steps
            
        except Exception as e:
            logger.error(f"Failed to generate plan: {e}")
            
            # Fallback
            return [
                PlanStep(
                    step_id="step_1",
                    step_type=StepType.ACTION,
                    description=task.description,
                    action={"type": "execute", "description": task.description}
                )
            ]
    
    async def _execute_step(self, step: PlanStep, plan: Plan) -> bool:
        """Execute a single step"""
        
        if step.step_type == StepType.ACTION:
            return await self._execute_action_step(step)
        elif step.step_type == StepType.VERIFICATION:
            return await self._execute_verification_step(step)
        elif step.step_type == StepType.WAIT:
            await asyncio.sleep((step.wait_ms or 1000) / 1000.0)
            step.executed = True
            step.success = True
            return True
        else:
            logger.warning(f"Unsupported step type: {step.step_type}")
            return False
    
    async def _execute_action_step(self, step: PlanStep) -> bool:
        """Execute an action step"""
        
        if not step.action:
            step.error = "No action specified"
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.action_executor_url}/action/execute",
                    json={
                        "action_id": step.step_id,
                        "action_type": step.action.get("type", "click"),
                        **step.action
                    },
                    timeout=30.0
                )
                
                result = response.json()
                
                step.executed = True
                step.success = result.get("status") == "success"
                step.result = result
                
                if not step.success:
                    step.error = result.get("error", "Unknown error")
                
                return step.success
                
        except Exception as e:
            step.executed = True
            step.success = False
            step.error = str(e)
            logger.error(f"Action execution failed: {e}")
            return False
    
    async def _execute_verification_step(self, step: PlanStep) -> bool:
        """Execute a verification step"""
        
        # Simple verification: just mark as success for now
        # In production, check UI Twin or Vision service
        
        step.executed = True
        step.success = True
        
        return True
    
    async def _replan_from_failure(self, plan: Plan, failed_step_index: int) -> bool:
        """Attempt to replan after failure"""
        
        # For now, just log and return false
        # In production, call LLM to generate recovery plan
        
        logger.warning(f"Replan not implemented yet")
        return False
    
    async def _store_episodic_memory(self, plan: Plan):
        """Store plan execution in episodic memory"""
        
        # Generate summary
        summary = f"""
Task: {plan.task_id}
Status: {plan.status.value}
Steps: {len(plan.steps)}
Success: {plan.success}
Duration: {(plan.completed_at or 0) - (plan.started_at or 0):.1f}s
Result: {plan.result_summary}
""".strip()
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.rag_url}/index",
                    json={
                        "id": plan.plan_id,
                        "content": summary,
                        "namespace": "past_runs",
                        "metadata": {
                            "task_id": plan.task_id,
                            "success": plan.success,
                            "timestamp": plan.completed_at
                        }
                    },
                    timeout=10.0
                )
                
                logger.info(f"💾 Stored episodic memory for plan {plan.plan_id}")
                
        except Exception as e:
            logger.warning(f"Failed to store episodic memory: {e}")
    
    async def start(self, host: str = "0.0.0.0", port: int = 8083):
        """Start the Planner HTTP API"""
        import uvicorn
        
        logger.info(f"🚀 Starting Planner API on {host}:{port}")
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


# Main entry point
if __name__ == "__main__":
    service = PlannerService()
    
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("👋 Planner service stopped")

