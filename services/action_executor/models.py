"""
Data models for Action Executor service
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum


class ActionType(str, Enum):
    """Supported action types"""
    CLICK = "click"
    TYPE = "type"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"


class ActionStatus(str, Enum):
    """Action execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Action(BaseModel):
    """Action to be executed"""
    
    action_id: str = Field(..., description="Unique action identifier")
    action_type: ActionType = Field(..., description="Type of action")
    element_id: Optional[str] = Field(None, description="Target element ID")
    element_selector: Optional[Dict[str, Any]] = Field(None, description="Element selector if ID not available")
    
    # Action-specific parameters
    text: Optional[str] = Field(None, description="Text to type (for TYPE action)")
    key: Optional[str] = Field(None, description="Key to press (for PRESS_KEY action)")
    x: Optional[int] = Field(None, description="X coordinate (for CLICK/DRAG)")
    y: Optional[int] = Field(None, description="Y coordinate (for CLICK/DRAG)")
    scroll_amount: Optional[int] = Field(None, description="Scroll amount in pixels")
    
    # Execution options
    confirm: bool = Field(default=False, description="Require confirmation before execution")
    timeout_ms: int = Field(default=5000, description="Timeout in milliseconds")
    verify_after: bool = Field(default=True, description="Verify action success after execution")
    screenshot_before: bool = Field(default=False, description="Take screenshot before action")
    screenshot_after: bool = Field(default=True, description="Take screenshot after action")
    
    # Metadata
    meta: Dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Result of action execution"""
    
    action_id: str
    status: ActionStatus
    result: str = Field(default="", description="Human-readable result message")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    # Timing
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: Optional[float] = None
    
    # Verification
    verified: bool = Field(default=False, description="Whether action was verified")
    screenshot_before_id: Optional[str] = None
    screenshot_after_id: Optional[str] = None
    
    # Metadata
    meta: Dict[str, Any] = Field(default_factory=dict)

