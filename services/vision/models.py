"""
Data models for Vision service
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple, Optional


class BoundingBox(BaseModel):
    """Bounding box coordinates"""
    x1: int
    y1: int
    x2: int
    y2: int
    
    @property
    def center(self) -> Tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)
    
    @property
    def width(self) -> int:
        return self.x2 - self.x1
    
    @property
    def height(self) -> int:
        return self.y2 - self.y1


class OCRResult(BaseModel):
    """Result of OCR on a region"""
    text: str
    confidence: float
    bbox: BoundingBox
    language: str = "en"


class DetectedObject(BaseModel):
    """Detected UI object"""
    label: str
    confidence: float
    bbox: BoundingBox
    attributes: Dict[str, Any] = Field(default_factory=dict)


class VisionResult(BaseModel):
    """Result of vision processing"""
    
    frame_id: str
    timestamp: float
    
    # OCR results
    ocr_texts: List[OCRResult] = Field(default_factory=list)
    
    # Object detection
    detected_objects: List[DetectedObject] = Field(default_factory=list)
    
    # Screen description (from VLM)
    description: Optional[str] = None
    
    # Metadata
    resolution: Tuple[int, int] = (0, 0)
    processing_time_ms: float = 0.0
    meta: Dict[str, Any] = Field(default_factory=dict)

