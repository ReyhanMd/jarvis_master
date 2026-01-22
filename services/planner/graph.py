"""
LangGraph workflow for planner with state serialization for WebSocket broadcasting
"""

import sys
import os
from typing import TypedDict, Annotated, Optional, List, Dict, Any
from loguru import logger
from shail.orchestration.checkpointing import create_checkpointer

# Handle imports for both module and direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)  # services/
_project_root = os.path.dirname(_parent_dir)  # project root
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Optional: LangGraph
try:
    from langgraph.graph import StateGraph, END
    HAS_LANGGRAPH = True
except ImportError:
    logger.warning("langgraph not installed - graph functionality limited")
    HAS_LANGGRAPH = False


class PlannerState(TypedDict, total=False):
    """State for planner graph"""
    task_description: str
    context: List[str]
    plan_steps: List[Dict]
    current_step: int
    execution_results: List[Dict]
    status: str
    error: Optional[str]
    agent_history: List[Dict[str, Any]]
    tool_history: List[Dict[str, Any]]
    recovery_attempts: int
    permission_requests: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    metadata: Dict[str, Any]


def create_planner_graph(planner_service, persistent: bool = True):
    """
    Create LangGraph workflow for planning and execution.
    
    Nodes:
    1. retrieve_context - Get RAG context
    2. generate_plan - Create step-by-step plan
    3. execute_step - Execute current step
    4. verify_step - Verify step result
    5. replan - Replan on failure
    6. finalize - Complete execution
    
    Flow:
    retrieve_context -> generate_plan -> execute_step -> verify_step
                                              ↓              ↓
                                         (success)      (failure)
                                              ↓              ↓
                                         next_step      replan -> execute_step
                                              ↓
                                         finalize
    """
    
    if not HAS_LANGGRAPH:
        # Return a simple stub
        class StubGraph:
            async def ainvoke(self, state):
                return state
        
        return StubGraph()
    
    # Define nodes
    async def retrieve_context(state: PlannerState):
        """Retrieve context from RAG"""
        logger.info("🔍 Retrieving context...")
        # Implementation would call RAG service
        return state
    
    async def generate_plan(state: PlannerState):
        """Generate execution plan"""
        logger.info("📋 Generating plan...")
        # Implementation would call LLM
        return state
    
    async def execute_step(state: PlannerState):
        """Execute current step"""
        logger.info(f"▶️  Executing step {state['current_step']}...")
        # Implementation would call action executor
        return state
    
    async def verify_step(state: PlannerState):
        """Verify step result"""
        logger.info("✓ Verifying step...")
        # Implementation would check UI Twin or Vision
        return state
    
    async def replan(state: PlannerState):
        """Replan on failure"""
        logger.info("🔄 Replanning...")
        # Implementation would call LLM for recovery plan
        return state
    
    async def finalize(state: PlannerState):
        """Finalize execution"""
        logger.info("✅ Finalizing...")
        state["status"] = "completed"
        return state
    
    # Build graph
    workflow = StateGraph(PlannerState)
    
    # Add nodes
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_plan", generate_plan)
    workflow.add_node("execute_step", execute_step)
    workflow.add_node("verify_step", verify_step)
    workflow.add_node("replan", replan)
    workflow.add_node("finalize", finalize)
    
    # Add edges
    workflow.set_entry_point("retrieve_context")
    workflow.add_edge("retrieve_context", "generate_plan")
    workflow.add_edge("generate_plan", "execute_step")
    workflow.add_edge("execute_step", "verify_step")
    
    # Conditional edges from verify_step
    def should_continue(state: PlannerState):
        if state.get("error"):
            return "replan"
        elif state["current_step"] < len(state["plan_steps"]) - 1:
            return "execute_step"
        else:
            return "finalize"
    
    workflow.add_conditional_edges(
        "verify_step",
        should_continue,
        {
            "execute_step": "execute_step",
            "replan": "replan",
            "finalize": "finalize"
        }
    )
    
    workflow.add_edge("replan", "execute_step")
    workflow.add_edge("finalize", END)
    
    checkpointer = create_checkpointer(persistent=persistent)
    return workflow.compile(checkpointer=checkpointer)


def serialize_graph_state(state: PlannerState, graph_instance=None) -> Dict[str, Any]:
    """
    Serialize LangGraph state to JSON-serializable format for WebSocket broadcasting.
    
    Args:
        state: PlannerState from LangGraph
        graph_instance: Optional compiled graph instance for metadata
    
    Returns:
        Dictionary with serialized state including nodes, edges, current node, etc.
    """
    serialized = {
        "task_description": state.get("task_description", ""),
        "current_step": state.get("current_step", 0),
        "status": state.get("status", "unknown"),
        "error": state.get("error"),
        "plan_steps": state.get("plan_steps", []),
        "execution_results": state.get("execution_results", []),
        "context": state.get("context", []),
        "agent_history": state.get("agent_history", []),
        "tool_history": state.get("tool_history", []),
        "recovery_attempts": state.get("recovery_attempts", 0),
        "permission_requests": state.get("permission_requests", []),
        "events": state.get("events", []),
    }
    
    # Add graph structure if available
    if graph_instance:
        # Extract nodes
        nodes = []
        edges = []
        
        # Try to get nodes from graph structure
        if hasattr(graph_instance, "nodes"):
            if hasattr(graph_instance.nodes, "keys"):
                nodes = list(graph_instance.nodes.keys())
            elif isinstance(graph_instance.nodes, dict):
                nodes = list(graph_instance.nodes.keys())
            elif hasattr(graph_instance.nodes, "__iter__"):
                nodes = list(graph_instance.nodes)
        
        # Extract edges from graph structure
        # LangGraph stores edges in the graph's structure
        if hasattr(graph_instance, "edges"):
            if isinstance(graph_instance.edges, dict):
                # Extract edges from dict structure
                for source, targets in graph_instance.edges.items():
                    if isinstance(targets, list):
                        for target in targets:
                            edges.append({"from": source, "to": target})
                    elif isinstance(targets, dict):
                        for target, condition in targets.items():
                            edges.append({"from": source, "to": target, "condition": condition})
                    else:
                        edges.append({"from": source, "to": targets})
            elif hasattr(graph_instance.edges, "__iter__"):
                edges = list(graph_instance.edges)
        
        # If we couldn't extract edges, define them based on known graph structure
        if not edges and nodes:
            # Define edges based on the planner graph structure
            known_edges = [
                {"from": "retrieve_context", "to": "generate_plan"},
                {"from": "generate_plan", "to": "execute_step"},
                {"from": "execute_step", "to": "verify_step"},
                {"from": "verify_step", "to": "execute_step", "condition": "continue"},
                {"from": "verify_step", "to": "replan", "condition": "error"},
                {"from": "verify_step", "to": "finalize", "condition": "complete"},
                {"from": "replan", "to": "execute_step"},
                {"from": "finalize", "to": "END"}
            ]
            # Only include edges where both nodes exist
            edges = [e for e in known_edges if e.get("from") in nodes and (e.get("to") in nodes or e.get("to") == "END")]
        
        serialized["nodes"] = nodes if nodes else ["retrieve_context", "generate_plan", "execute_step", "verify_step", "replan", "finalize"]
        serialized["edges"] = edges if edges else [
            {"from": "retrieve_context", "to": "generate_plan"},
            {"from": "generate_plan", "to": "execute_step"},
            {"from": "execute_step", "to": "verify_step"},
            {"from": "verify_step", "to": "execute_step", "condition": "continue"},
            {"from": "verify_step", "to": "replan", "condition": "error"},
            {"from": "verify_step", "to": "finalize", "condition": "complete"},
            {"from": "replan", "to": "execute_step"},
            {"from": "finalize", "to": "END"}
        ]
    
    # Determine current node based on state
    current_node = "unknown"
    status = state.get("status", "")
    
    if status == "planning":
        current_node = "generate_plan"
    elif status == "executing":
        step = state.get("current_step", 0)
        if step < len(state.get("plan_steps", [])):
            current_node = "execute_step"
        else:
            current_node = "finalize"
    elif status == "verifying":
        current_node = "verify_step"
    elif status == "replanning":
        current_node = "replan"
    elif status == "completed":
        current_node = "finalize"
    elif state.get("error"):
        current_node = "replan"
    
    serialized["current_node"] = current_node
    
    # Add metadata
    serialized["metadata"] = {
        "has_error": bool(state.get("error")),
        "step_count": len(state.get("plan_steps", [])),
        "completed_steps": state.get("current_step", 0),
        "has_context": len(state.get("context", [])) > 0,
        "recovery_attempts": state.get("recovery_attempts", 0),
        "agent_history_length": len(state.get("agent_history", [])),
        "tool_history_length": len(state.get("tool_history", [])),
    }
    
    return serialized

