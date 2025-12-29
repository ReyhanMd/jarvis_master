"""Project context storage for RAG memory.

This module provides storage for project context, user intents, tool configurations,
and workflow patterns that SHAIL can use to understand ongoing work.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from shail.memory.store import _conn

logger = logging.getLogger(__name__)


PROJECT_CONTEXT_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_context (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_name TEXT NOT NULL,
  context_type TEXT NOT NULL,  -- 'intent', 'config', 'pattern', 'note'
  content_json TEXT NOT NULL,
  metadata_json TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS architecture_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_type TEXT NOT NULL,  -- 'module', 'dependency', 'integration', 'design'
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata_json TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_context_name ON project_context(project_name);
CREATE INDEX IF NOT EXISTS idx_project_context_type ON project_context(context_type);
CREATE INDEX IF NOT EXISTS idx_architecture_type ON architecture_notes(note_type);
"""


def _init_schema():
    """Initialize project context schema."""
    cx = _conn()
    try:
        cx.executescript(PROJECT_CONTEXT_SCHEMA)
        cx.commit()
    finally:
        cx.close()


def store_project_context(
    project_name: str,
    context_type: str,
    content: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store project context information.
    
    Args:
        project_name: Name of the project
        context_type: Type of context ('intent', 'config', 'pattern', 'note')
        content: Context content dictionary
        metadata: Optional metadata
        
    Returns:
        ID of the stored context
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            """INSERT INTO project_context (project_name, context_type, content_json, metadata_json)
               VALUES (?, ?, ?, ?)""",
            (
                project_name,
                context_type,
                json.dumps(content),
                json.dumps(metadata) if metadata else None,
            )
        )
        cx.commit()
        context_id = cur.lastrowid
        logger.debug(f"Stored project context: {project_name}/{context_type} (id: {context_id})")
        return context_id
    
    finally:
        cx.close()


def get_project_context(
    project_name: str,
    context_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get project context information.
    
    Args:
        project_name: Name of the project
        context_type: Optional filter by context type
        limit: Maximum number of records to return
        
    Returns:
        List of context records
    """
    _init_schema()
    cx = _conn()
    try:
        query = "SELECT * FROM project_context WHERE project_name = ?"
        params = [project_name]
        
        if context_type:
            query += " AND context_type = ?"
            params.append(context_type)
        
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        
        cur = cx.execute(query, params)
        rows = cur.fetchall()
        
        # Get column names
        columns = [desc[0] for desc in cur.description]
        
        contexts = []
        for row in rows:
            record = dict(zip(columns, row))
            # Parse JSON fields
            if record.get("content_json"):
                record["content"] = json.loads(record["content_json"])
            if record.get("metadata_json"):
                record["metadata"] = json.loads(record["metadata_json"])
            # Remove JSON fields
            record.pop("content_json", None)
            record.pop("metadata_json", None)
            contexts.append(record)
        
        return contexts
    
    finally:
        cx.close()


def store_user_intent(
    project_name: str,
    intent: str,
    details: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store a user intent for a project.
    
    Args:
        project_name: Name of the project
        intent: Description of the user's intent
        details: Optional additional details
        
    Returns:
        ID of the stored intent
    """
    content = {"intent": intent}
    if details:
        content.update(details)
    return store_project_context(project_name, "intent", content)


def store_tool_config(
    project_name: str,
    tool_name: str,
    config: Dict[str, Any],
) -> int:
    """
    Store tool configuration for a project.
    
    Args:
        project_name: Name of the project
        tool_name: Name of the tool
        config: Configuration dictionary
        
    Returns:
        ID of the stored config
    """
    content = {"tool_name": tool_name, "config": config}
    return store_project_context(project_name, "config", content)


def store_workflow_pattern(
    project_name: str,
    pattern: Dict[str, Any],
    description: Optional[str] = None,
) -> int:
    """
    Store a workflow pattern for a project.
    
    Args:
        project_name: Name of the project
        pattern: Pattern dictionary (e.g., sequence of tools, conditions)
        description: Optional description of the pattern
        
    Returns:
        ID of the stored pattern
    """
    content = {"pattern": pattern}
    if description:
        content["description"] = description
    return store_project_context(project_name, "pattern", content)


def store_architecture_note(
    note_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Store an architecture note.
    
    Args:
        note_type: Type of note ('module', 'dependency', 'integration', 'design')
        title: Title of the note
        content: Content of the note
        metadata: Optional metadata
        
    Returns:
        ID of the stored note
    """
    _init_schema()
    cx = _conn()
    try:
        cur = cx.execute(
            """INSERT INTO architecture_notes (note_type, title, content, metadata_json)
               VALUES (?, ?, ?, ?)""",
            (
                note_type,
                title,
                content,
                json.dumps(metadata) if metadata else None,
            )
        )
        cx.commit()
        note_id = cur.lastrowid
        logger.debug(f"Stored architecture note: {title} (id: {note_id})")
        return note_id
    
    finally:
        cx.close()


def get_architecture_notes(
    note_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get architecture notes.
    
    Args:
        note_type: Optional filter by note type
        limit: Maximum number of records to return
        
    Returns:
        List of architecture note records
    """
    _init_schema()
    cx = _conn()
    try:
        query = "SELECT * FROM architecture_notes WHERE 1=1"
        params = []
        
        if note_type:
            query += " AND note_type = ?"
            params.append(note_type)
        
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        
        cur = cx.execute(query, params)
        rows = cur.fetchall()
        
        # Get column names
        columns = [desc[0] for desc in cur.description]
        
        notes = []
        for row in rows:
            record = dict(zip(columns, row))
            # Parse JSON fields
            if record.get("metadata_json"):
                record["metadata"] = json.loads(record["metadata_json"])
            # Remove JSON field
            record.pop("metadata_json", None)
            notes.append(record)
        
        return notes
    
    finally:
        cx.close()
