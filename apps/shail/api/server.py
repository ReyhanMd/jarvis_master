"""
SHAIL Brain API Layer

This module exposes the Symbiotic OS logic (MasterPlanner) via a REST API.
This allows the macOS Native UI (Swift) to communicate with the Python Brain.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
# This ensures we can import 'shail' regardless of where this script is run from
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from shail.orchestration.master_planner import MasterPlanner
from shail.orchestration.context_detector import ProjectContextDetector
from shail.core.types import TaskRequest, RoutingDecision
from apps.shail.settings import get_settings
from shail.memory.rag import get_project_context_from_rag

app = FastAPI(title="SHAIL Symbiotic Brain API", version="1.0.0")

# Initialize the Brain (MasterPlanner)
# We do this at startup to load agents and models once
brain = MasterPlanner()

class ChatInput(BaseModel):
    message: str
    mode: Optional[str] = "auto"
    context_snapshots: Optional[List[str]] = [] # Paths to screenshots if any

class ChatResponse(BaseModel):
    decision: RoutingDecision
    agent_output: Optional[str] = None # For MVP, this might be the rationale or result

@app.get("/")
def health_check():
    return {"status": "online", "system": "Symbiotic OS"}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(input_data: ChatInput):
    """
    Primary endpoint for the UI to send user queries.
    Routes the request through the Symbiotic Controller.
    """
    print(f"[API] Received query: {input_data.message}")
    
    # 1. Create TaskRequest
    req = TaskRequest(
        text=input_data.message,
        mode=input_data.mode
        # Attachments could be handled here
    )
    
    # 2. Route through MasterPlanner (Symbiotic Brain)
    try:
        decision = brain.route_request(req)
        
        # 3. For MVP, if it was a Swaraj Loop result, the logic ran inside route_request
        # The 'rationale' often contains the result in our current mock setup.
        
        return ChatResponse(
            decision=decision,
            agent_output=decision.rationale 
        )
        
    except Exception as e:
        print(f"[API] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workflow_state")
def get_workflow_state():
    """
    Returns the current execution graph for the Bird's Eye View.
    Mock data for now until MasterPlanner is fully instrumented.
    """
    # This would normally come from brain.get_active_plan()
    return {
        "nodes": [
            {"id": "master", "name": "Gemini 3 Pro", "type": "Master", "status": "active", "position": {"x": 400, "y": 100}},
            {"id": "sub1", "name": "ChatGPT (Coding)", "type": "Sub", "status": "working", "position": {"x": 200, "y": 300}},
            {"id": "tool1", "name": "SolidWorks", "type": "Software", "status": "idle", "position": {"x": 200, "y": 450}},
        ],
        "edges": [
            {"from": "master", "to": "sub1"},
            {"from": "sub1", "to": "tool1"}
        ]
    }


@app.get("/context/project")
def get_project_context(name: Optional[str] = None):
    detector = ProjectContextDetector(brain.buffer)
    project_name = name or detector.detect_active_project()
    if not project_name:
        return {"project": None, "context": []}
    detector.persist_project_context(project_name)
    context = get_project_context_from_rag(project_name)
    return {"project": project_name, "context": context}

if __name__ == "__main__":
    settings = get_settings()
    # Run server on localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
