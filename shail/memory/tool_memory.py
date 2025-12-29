"""Tool state storage for RAG memory.

This module provides storage for tool states, allowing SHAIL to remember
what tools were used, their configurations, and their results.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from shail.memory.store import _conn

logger = logging.getLogger(__name__)


TOOL_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_states (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_name TEXT NOT NULL,
  tool_category TEXT,
  state_json TEXT NOT NULL,
  result_json TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_usage_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_name TEXT NOT NULL,
  tool_category TEXT,
  task_id TEXT,
  arguments_json TEXT,
  result_json TEXT,
  success BOOLEAN,
  error_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_states_name ON tool_states(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_usage_tool_name ON tool_usage_history(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_usage_task_id ON tool_usage_history(task_id);
"""


def _init_schema():
    """Initialize tool memory schema."""
    cx = _conn()
    try:
        cx.executescript(TOOL_MEMORY_SCHEMA)
        cx.commit()
    finally:
        cx.close()


def store_tool_state(
    tool_name: str,
    state: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
) -> int:
    """
    Store or update a tool's state.
    
    Args:
        tool_name: Name of the tool
        state: Current state of the tool
        result: Optional result from tool execution
        category: Optional category (e.g., "engineering", "api")
        
    Returns:
        ID of the stored state
    """
    _init_schema()
    cx = _conn()
    try:
        # Check if state exists for this tool
        cur = cx.execute(
            "SELECT id FROM tool_states WHERE tool_name = ? ORDER BY updated_at DESC LIMIT 1",
            (tool_name,)
        )
        existing = cur.fetchone()
        
        state_json = json.dumps(state)
        result_json = json.dumps(result) if result else None
        
        if existing:
            # Update existing state
            cx.execute(
                """UPDATE tool_states 
                   SET state_json = ?, result_json = ?, tool_category = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (state_json, result_json, category, existing[0])
            )
            state_id = existing[0]
        else:
            # Insert new state
            cur = cx.execute(
                """INSERT INTO tool_states (tool_name, tool_category, state_json, result_json)
                   VALUES (?, ?, ?, ?)""",
                (tool_name, category, state_json, result_json)
            )
            state_id = cur.lastrowid
        
        cx.commit()
        logger.debug(f"Stored tool state for {tool_name} (id: {state_id})")
        return state_id
    
    finally:
        cx.close()


def get_tool_state(tool_name: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest state for a tool.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Dictionary with state and result, or None if not found
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            """SELECT state_json, result_json, tool_category, updated_at
               FROM tool_states 
               WHERE tool_name = ? 
               ORDER BY updated_at DESC LIMIT 1""",
            (tool_name,)
        )
        row = cur.fetchone()
        
        if row:
            state_json, result_json, category, updated_at = row
            return {
                "tool_name": tool_name,
                "state": json.loads(state_json),
                "result": json.loads(result_json) if result_json else None,
                "category": category,
                "updated_at": updated_at,
            }
        return None
    
    finally:
        cx.close()


def log_tool_usage(
    tool_name: str,
    arguments: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    task_id: Optional[str] = None,
    category: Optional[str] = None,
) -> int:
    """
    Log a tool usage event.
    
    Args:
        tool_name: Name of the tool used
        arguments: Arguments passed to the tool
        result: Optional result from tool execution
        success: Whether the tool execution was successful
        error_message: Optional error message if failed
        task_id: Optional task ID that triggered this usage
        category: Optional category
        
    Returns:
        ID of the logged usage
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            """INSERT INTO tool_usage_history 
               (tool_name, tool_category, task_id, arguments_json, result_json, success, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                tool_name,
                category,
                task_id,
                json.dumps(arguments),
                json.dumps(result) if result else None,
                success,
                error_message,
            )
        )
        cx.commit()
        usage_id = cur.lastrowid
        logger.debug(f"Logged tool usage: {tool_name} (id: {usage_id})")
        return usage_id
    
    finally:
        cx.close()


def get_tool_usage_history(
    tool_name: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get tool usage history.
    
    Args:
        tool_name: Optional filter by tool name
        task_id: Optional filter by task ID
        limit: Maximum number of records to return
        
    Returns:
        List of usage history records
    """
    _init_schema()
    cx = _conn()
    try:
        query = "SELECT * FROM tool_usage_history WHERE 1=1"
        params = []
        
        if tool_name:
            query += " AND tool_name = ?"
            params.append(tool_name)
        
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        
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
            if record.get("arguments_json"):
                record["arguments"] = json.loads(record["arguments_json"])
            if record.get("result_json"):
                record["result"] = json.loads(record["result_json"])
            # Remove JSON fields
            record.pop("arguments_json", None)
            record.pop("result_json", None)
            history.append(record)
        
        return history
    
    finally:
        cx.close()
