from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class TaskStatus(str, Enum):
    """Task execution status states."""
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


class Attachment(BaseModel):
    name: str
    mime_type: Optional[str] = None
    content_b64: Optional[str] = None


class TaskRequest(BaseModel):
    text: str = Field(..., description="Primary instruction or request")
    mode: Optional[str] = Field(default="auto", description="auto|code|bio|robo|plasma|research")
    attachments: Optional[List[Attachment]] = None


class RoutingDecision(BaseModel):
    agent: str
    confidence: float
    rationale: str


class Artifact(BaseModel):
    kind: str
    path: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class PermissionRequest(BaseModel):
    """Represents a request for user approval to execute a potentially dangerous operation."""
    task_id: str = Field(..., description="Associated task ID")
    tool_name: str = Field(..., description="Name of the tool requiring permission")
    tool_args: Dict[str, Any] = Field(..., description="Arguments that will be passed to the tool")
    rationale: str = Field(..., description="Human-readable explanation of why this tool is being called")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the request was created")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskResult(BaseModel):
    status: TaskStatus = Field(..., description="Current status of the task")
    summary: str = Field(..., description="Human-readable summary of task execution or current state")
    agent: Optional[str] = Field(None, description="Agent that handled or is handling this task")
    artifacts: Optional[List[Artifact]] = Field(None, description="Files or data artifacts produced")
    audit_ref: Optional[str] = Field(None, description="Reference to audit log entry")
    permission_request: Optional[PermissionRequest] = Field(
        None, 
        description="Permission request if status is AWAITING_APPROVAL"
    )
    task_id: Optional[str] = Field(None, description="Unique identifier for this task")


