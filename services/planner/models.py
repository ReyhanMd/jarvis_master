"""
Data models for Planner service
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class PlanStatus(str, Enum):
    """Plan execution status"""
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepType(str, Enum):
    """Type of plan step"""
    ACTION = "action"
    VERIFICATION = "verification"
    WAIT = "wait"
    CONDITIONAL = "conditional"


class Task(BaseModel):
    """User task to be planned and executed"""
    
    task_id: str = Field(..., description="Unique task identifier")
    description: str = Field(..., description="Natural language task description")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    constraints: List[str] = Field(default_factory=list, description="Safety constraints")
    timeout_seconds: int = Field(default=300, description="Maximum execution time")


class PlanStep(BaseModel):
    """Single step in a plan"""
    
    step_id: str
    step_type: StepType
    description: str
    
    # For ACTION steps
    action: Optional[Dict[str, Any]] = None
    
    # For VERIFICATION steps
    precondition: Optional[str] = None
    postcondition: Optional[str] = None
    
    # For WAIT steps
    wait_ms: Optional[int] = None
    
    # For CONDITIONAL steps
    condition: Optional[str] = None
    if_true_goto: Optional[str] = None
    if_false_goto: Optional[str] = None
    
    # Execution result
    executed: bool = False
    success: Optional[bool] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class Plan(BaseModel):
    """Execution plan for a task"""
    
    plan_id: str
    task_id: str
    status: PlanStatus = PlanStatus.PENDING
    
    steps: List[PlanStep] = Field(default_factory=list)
    current_step: int = 0
    
    # Context from RAG retrieval
    retrieved_context: List[str] = Field(default_factory=list)
    
    # Timing
    created_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # Results
    success: bool = False
    result_summary: str = ""
    logs: List[str] = Field(default_factory=list)

