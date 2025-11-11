from pydantic import BaseModel
from typing import Optional, Any, Dict, List


class TaskRequest(BaseModel):
    text: str
    mode: Optional[str] = "default"  # default | code | bio | robo | plasma | research
    metadata: Optional[Dict[str, Any]] = None


class Artifact(BaseModel):
    kind: str
    uri: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class TaskResult(BaseModel):
    status: str
    summary: str
    artifacts: List[Artifact] = []
    logs_ref: Optional[str] = None


