"""Modification history system for SHAIL self-modification.

This module tracks all self-modification attempts, successes, and failures,
integrating with RAG for learning and tool-aware logging.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from shail.memory.store import _conn

logger = logging.getLogger(__name__)


SELF_MOD_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS self_modifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  modification_id TEXT UNIQUE NOT NULL,
  file_path TEXT NOT NULL,
  operation TEXT NOT NULL,  -- 'write', 'delete', 'create'
  old_content TEXT,
  new_content TEXT,
  diff_json TEXT,
  rationale TEXT,
  proposal_json TEXT,
  status TEXT NOT NULL,  -- 'pending', 'approved', 'rejected', 'completed', 'failed'
  success BOOLEAN,
  error_message TEXT,
  backup_path TEXT,
  tool_used TEXT,  -- Which tool/adapter was used
  mcp_tool_name TEXT,  -- MCP tool name if applicable
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_self_mod_file ON self_modifications(file_path);
CREATE INDEX IF NOT EXISTS idx_self_mod_status ON self_modifications(status);
CREATE INDEX IF NOT EXISTS idx_self_mod_created ON self_modifications(created_at);
"""


def _init_schema():
    """Initialize self-modification history schema."""
    cx = _conn()
    try:
        cx.executescript(SELF_MOD_HISTORY_SCHEMA)
        cx.commit()
    finally:
        cx.close()


def log_modification(
    modification_id: str,
    file_path: str,
    operation: str,
    old_content: Optional[str] = None,
    new_content: Optional[str] = None,
    diff: Optional[Dict[str, Any]] = None,
    rationale: Optional[str] = None,
    proposal: Optional[Dict[str, Any]] = None,
    status: str = "pending",
    backup_path: Optional[str] = None,
    tool_used: Optional[str] = None,
    mcp_tool_name: Optional[str] = None,
) -> int:
    """
    Log a self-modification attempt.
    
    Args:
        modification_id: Unique identifier for this modification
        file_path: Path to the modified file
        operation: Operation type ('write', 'delete', 'create')
        old_content: Original content
        new_content: New content
        diff: Diff dictionary
        rationale: Why this modification was made
        proposal: Improvement proposal dictionary
        status: Current status
        backup_path: Path to backup file
        tool_used: Tool/adapter used
        mcp_tool_name: MCP tool name if applicable
        
    Returns:
        ID of the logged modification
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            """INSERT INTO self_modifications 
               (modification_id, file_path, operation, old_content, new_content, 
                diff_json, rationale, proposal_json, status, backup_path, 
                tool_used, mcp_tool_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                modification_id,
                file_path,
                operation,
                old_content,
                new_content,
                json.dumps(diff) if diff else None,
                rationale,
                json.dumps(proposal) if proposal else None,
                status,
                backup_path,
                tool_used,
                mcp_tool_name,
            )
        )
        cx.commit()
        mod_id = cur.lastrowid
        logger.info(f"Logged modification: {modification_id} (id: {mod_id})")
        return mod_id
    
    finally:
        cx.close()


def update_modification_status(
    modification_id: str,
    status: str,
    success: Optional[bool] = None,
    error_message: Optional[str] = None,
) -> bool:
    """
    Update the status of a modification.
    
    Args:
        modification_id: Modification ID
        status: New status
        success: Whether the modification was successful
        error_message: Optional error message
        
    Returns:
        True if updated successfully
    """
    _init_schema()
    cx = _conn()
    try:
        completed_at = datetime.now().isoformat() if status in ("completed", "failed", "rejected") else None
        
        cx.execute(
            """UPDATE self_modifications 
               SET status = ?, success = ?, error_message = ?, 
                   updated_at = CURRENT_TIMESTAMP, completed_at = ?
               WHERE modification_id = ?""",
            (status, success, error_message, completed_at, modification_id)
        )
        cx.commit()
        logger.info(f"Updated modification {modification_id} to status: {status}")
        return True
    
    finally:
        cx.close()


def get_modification_history(
    file_path: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get modification history.
    
    Args:
        file_path: Optional filter by file path
        status: Optional filter by status
        limit: Maximum number of records
        
    Returns:
        List of modification records
    """
    _init_schema()
    cx = _conn()
    try:
        query = "SELECT * FROM self_modifications WHERE 1=1"
        params = []
        
        if file_path:
            query += " AND file_path = ?"
            params.append(file_path)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cur = cx.execute(query, params)
        rows = cur.fetchall()
        
        # Get column names
        columns = [desc[0] for desc in cur.description]
        
        history = []
        for row in rows:
            record = dict(zip(columns, row))
            # Parse JSON fields
            if record.get("diff_json"):
                record["diff"] = json.loads(record["diff_json"])
            if record.get("proposal_json"):
                record["proposal"] = json.loads(record["proposal_json"])
            # Remove JSON fields
            record.pop("diff_json", None)
            record.pop("proposal_json", None)
            history.append(record)
        
        return history
    
    finally:
        cx.close()


def get_modification(modification_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific modification by ID.
    
    Args:
        modification_id: Modification ID
        
    Returns:
        Modification record or None
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            "SELECT * FROM self_modifications WHERE modification_id = ?",
            (modification_id,)
        )
        row = cur.fetchone()
        
        if row:
            columns = [desc[0] for desc in cur.description]
            record = dict(zip(columns, row))
            # Parse JSON fields
            if record.get("diff_json"):
                record["diff"] = json.loads(record["diff_json"])
            if record.get("proposal_json"):
                record["proposal"] = json.loads(record["proposal_json"])
            record.pop("diff_json", None)
            record.pop("proposal_json", None)
            return record
        
        return None
    
    finally:
        cx.close()
