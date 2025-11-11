"""
Permission Manager - Tracks and manages user approvals for potentially dangerous operations.

This module provides:
- In-memory tracking of pending permission requests
- SQLite persistence for audit trail
- Approval/denial handling with state management
"""

import sqlite3
import os
import json
from typing import Optional, Dict
from datetime import datetime
from shail.core.types import PermissionRequest
from shail.safety.exceptions import PermissionDenied
from apps.shail.settings import get_settings


# In-memory store for active permission requests (keyed by task_id)
_pending_permissions: Dict[str, PermissionRequest] = {}

# Set of task IDs that are currently being executed with approved permissions
# This allows tools to check if they should proceed even if they'd normally require permission
_approved_execution_context: set = set()


PERMISSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS permissions (
    task_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    tool_args_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_at DATETIME NOT NULL,
    resolved_at DATETIME,
    resolved_by TEXT
);
"""


def _get_db_connection():
    """Get SQLite connection with permissions table initialized."""
    settings = get_settings()
    db_dir = os.path.dirname(settings.sqlite_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(settings.sqlite_path)
    conn.execute(PERMISSIONS_SCHEMA)
    conn.commit()
    return conn


class PermissionManager:
    """
    Manages permission requests, approvals, and denials.
    
    Maintains both in-memory state (for fast lookups) and SQLite persistence
    (for audit trail and recovery).
    """
    
    @staticmethod
    def request_permission(
        task_id: str,
        tool_name: str,
        tool_args: dict,
        rationale: str
    ) -> PermissionRequest:
        """
        Register a new permission request.
        
        Args:
            task_id: Unique identifier for the associated task
            tool_name: Name of the tool requiring permission
            tool_args: Arguments that will be passed to the tool
            rationale: Human-readable explanation
            
        Returns:
            PermissionRequest object
        """
        permission_req = PermissionRequest(
            task_id=task_id,
            tool_name=tool_name,
            tool_args=tool_args,
            rationale=rationale,
            timestamp=datetime.utcnow()
        )
        
        # Store in memory for fast access
        _pending_permissions[task_id] = permission_req
        
        # Persist to database for audit trail
        conn = _get_db_connection()
        try:
            conn.execute(
                """INSERT INTO permissions 
                   (task_id, tool_name, tool_args_json, rationale, status, requested_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    tool_name,
                    json.dumps(tool_args),
                    rationale,
                    "pending",
                    permission_req.timestamp.isoformat()
                )
            )
            conn.commit()
        finally:
            conn.close()
        
        return permission_req
    
    @staticmethod
    def get_pending(task_id: str) -> Optional[PermissionRequest]:
        """
        Retrieve a pending permission request by task_id.
        
        Args:
            task_id: Task ID to look up
            
        Returns:
            PermissionRequest if found and still pending, None otherwise
        """
        # Check in-memory first
        if task_id in _pending_permissions:
            return _pending_permissions[task_id]
        
        # Fallback to database
        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                """SELECT tool_name, tool_args_json, rationale, requested_at
                   FROM permissions
                   WHERE task_id = ? AND status = 'pending'""",
                (task_id,)
            )
            row = cursor.fetchone()
            if row:
                tool_name, tool_args_json, rationale, requested_at = row
                return PermissionRequest(
                    task_id=task_id,
                    tool_name=tool_name,
                    tool_args=json.loads(tool_args_json),
                    rationale=rationale,
                    timestamp=datetime.fromisoformat(requested_at)
                )
            return None
        finally:
            conn.close()
    
    @staticmethod
    def approve(task_id: str, resolved_by: str = "user") -> bool:
        """
        Approve a pending permission request.
        
        Args:
            task_id: Task ID of the request to approve
            resolved_by: Identifier for who/what approved (default: "user")
            
        Returns:
            True if approval was successful, False if request not found
            
        Raises:
            PermissionDenied: If the request was already denied
        """
        # Check current status in database
        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT status FROM permissions WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            status = row[0]
            if status == "denied":
                raise PermissionDenied(task_id, "previously denied")
            if status == "approved":
                return True  # Already approved, idempotent
            
            # Update to approved
            conn.execute(
                """UPDATE permissions
                   SET status = 'approved', resolved_at = ?, resolved_by = ?
                   WHERE task_id = ?""",
                (datetime.utcnow().isoformat(), resolved_by, task_id)
            )
            conn.commit()
            
            # Remove from in-memory cache (approved requests don't need to stay in memory)
            _pending_permissions.pop(task_id, None)
            
            return True
        finally:
            conn.close()
    
    @staticmethod
    def deny(task_id: str, resolved_by: str = "user") -> bool:
        """
        Deny a pending permission request.
        
        Args:
            task_id: Task ID of the request to deny
            resolved_by: Identifier for who/what denied (default: "user")
            
        Returns:
            True if denial was successful, False if request not found
        """
        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT status FROM permissions WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False
            
            status = row[0]
            if status in ("denied", "approved"):
                return True  # Already resolved, idempotent
            
            # Update to denied
            conn.execute(
                """UPDATE permissions
                   SET status = 'denied', resolved_at = ?, resolved_by = ?
                   WHERE task_id = ?""",
                (datetime.utcnow().isoformat(), resolved_by, task_id)
            )
            conn.commit()
            
            # Remove from in-memory cache
            _pending_permissions.pop(task_id, None)
            
            return True
        finally:
            conn.close()
    
    @staticmethod
    def is_approved(task_id: str) -> bool:
        """
        Check if a permission request has been approved.
        
        Args:
            task_id: Task ID to check
            
        Returns:
            True if approved, False otherwise
        """
        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT status FROM permissions WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            return row and row[0] == "approved"
        finally:
            conn.close()
    
    @staticmethod
    def is_denied(task_id: str) -> bool:
        """
        Check if a permission request has been denied.
        
        Args:
            task_id: Task ID to check
            
        Returns:
            True if denied, False otherwise
        """
        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT status FROM permissions WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            return row and row[0] == "denied"
        finally:
            conn.close()
    
    @staticmethod
    def add_approved_context(task_id: str) -> None:
        """
        Add a task_id to the approved execution context.
        Tools can check this before raising PermissionRequired.
        
        Args:
            task_id: Task ID to mark as approved for execution
        """
        _approved_execution_context.add(task_id)
    
    @staticmethod
    def remove_approved_context(task_id: str) -> None:
        """
        Remove a task_id from the approved execution context.
        
        Args:
            task_id: Task ID to remove
        """
        _approved_execution_context.discard(task_id)
    
    @staticmethod
    def is_in_approved_context(task_id: str) -> bool:
        """
        Check if a task_id is in the approved execution context.
        
        Args:
            task_id: Task ID to check
            
        Returns:
            True if task is approved for execution
        """
        return task_id in _approved_execution_context or PermissionManager.is_approved(task_id)

