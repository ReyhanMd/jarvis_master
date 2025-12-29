"""
Data models for UI Twin service
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Tuple, Optional
import time


class UIElement(BaseModel):
    """Represents a single UI element in the digital twin"""
    
    id: str = Field(..., description="Unique element identifier")
    role: str = Field(..., description="UI role (button, text field, etc)")
    text: str = Field(default="", description="Element text content")
    title: str = Field(default="", description="Element title/label")
    bbox: Tuple[int, int, int, int] = Field(default=(0, 0, 0, 0), description="Bounding box (x1, y1, x2, y2)")
    window: str = Field(default="", description="Parent window identifier")
    app_name: str = Field(default="", description="Application name")
    last_seen: float = Field(default_factory=time.time, description="Last update timestamp")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        frozen = False


class UISnapshot(BaseModel):
    """Snapshot of UI state at a point in time"""
    
    timestamp: float = Field(default_factory=time.time)
    delta: Dict[str, Any] = Field(..., description="Changed elements or events")
    snapshot_type: str = Field(default="delta", description="Type: full, delta, event")
    
    class Config:
        frozen = False


class ElementSelector(BaseModel):
    """Selector for finding UI elements"""
    
    role: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    window: Optional[str] = None
    app_name: Optional[str] = None
    bbox: Optional[Tuple[int, int, int, int]] = None

