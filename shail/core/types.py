from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
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
    desktop_id: Optional[str] = Field(default=None, description="Desktop context ID for multi-desktop support")


class RoutingDecision(BaseModel):
    agent: str
    confidence: float
    rationale: str
    guidance_request: Optional["UserGuidanceRequest"] = None


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


class ChatRequest(BaseModel):
    """Request for direct LLM chat conversation."""
    text: str = Field(..., description="Message text to send to LLM")
    attachments: Optional[List[Attachment]] = Field(
        None, 
        description="Optional image attachments (base64 encoded)"
    )


class ChatResponse(BaseModel):
    """Response from direct LLM chat conversation."""
    text: str = Field(..., description="LLM response text")
    model: str = Field(..., description="Model used for generation")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Response timestamp")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class NarrativeSegment(BaseModel):
    """
    Represents a specific time segment in the user's history, 
    enriched with a narrative story.
    """
    start_time: float
    end_time: float
    story: str = Field(..., description="Natural language summary of what happened in this segment")
    raw_logs: Optional[List[str]] = Field(default=[], description="Raw accessibility logs if available")
    thumbnail_path: Optional[str] = Field(None, description="Path to a representative thumbnail")


class GroundingResult(BaseModel):
    """Result from the Grounding Agent."""
    segment: Optional[NarrativeSegment] = None
    confidence: float = Field(..., description="0.0 to 1.0 confidence in this match")
    rationale: str = Field(..., description="Why this segment was chosen")


class VisionObservation(BaseModel):
    """Result from the Vision Agent."""
    text: str = Field(..., description="The observed textual content/code")
    detected_anomalies: List[str] = Field(default=[], description="List of specific errors/bugs found")
    is_anomaly: bool = Field(default=False, description="Whether this observation contains a critical anomaly")


# ------------------------------
# Perception Layer Core Models
# ------------------------------

@dataclass
class AccessibilityEvent:
    ts: float
    app_name: str
    role: str
    label: Optional[str]
    value: Optional[str]
    focused: bool
    metadata: Dict[str, Any]


@dataclass
class ThumbnailFrame:
    ts: float
    path: str
    width: int
    height: int
    hash: str


class FrameRequest(BaseModel):
    request_id: str
    start_ts: float
    end_ts: float
    fps: int = 2
    max_frames: int = 10
    resolution: Dict[str, int] = Field(default_factory=lambda: {"width": 1920, "height": 1080})


class FrameResponse(BaseModel):
    request_id: str
    frames: List[Dict[str, Any]]
    status: str


class UserGuidanceRequest(BaseModel):
    task_id: Optional[str] = None
    original_query: str
    attempts: int
    last_confidence: float
    suggested_clarifications: List[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)



