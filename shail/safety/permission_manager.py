"""
Permission Manager - Tracks and manages user approvals for potentially dangerous operations.

This module provides:
- In-memory tracking of pending permission requests
- SQLite persistence for audit trail
- Approval/denial handling with state management
- WebSocket notifications for real-time UI updates
"""

import sqlite3
import os
import json
import logging
from typing import Optional, Dict
from datetime import datetime
from shail.core.types import PermissionRequest
from shail.safety.exceptions import PermissionDenied
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)


# In-memory store for active permission requests (keyed by task_id)
_pending_permissions: Dict[str, PermissionRequest] = {}

# Set of task IDs that are currently being executed with approved permissions
# This allows tools to check if they should proceed even if they'd normally require permission
_approved_execution_context: set = set()


def _broadcast_permission_request(permission_req: PermissionRequest):
    """Broadcast permission request via WebSocket (non-blocking, thread-safe).

    Production-safe across three caller contexts:
      • Loop running in this thread          → schedule on it
      • Loop running on main thread (other)  → run_coroutine_threadsafe
      • No loop anywhere                     → swallow (best-effort delivery)

    Never calls asyncio.run() — would crash inside FastAPI request handlers.
    Never raises — WebSocket delivery is best-effort.
    """
    try:
        from apps.shail.websocket_server import websocket_manager
        import asyncio
    except Exception as exc:
        logger.debug("WebSocket import failed: %s", exc)
        return

    event_data = {
        "task_id":   permission_req.task_id,
        "tool_name": permission_req.tool_name,
        "tool_args": permission_req.tool_args,
        "rationale": permission_req.rationale,
        "timestamp": permission_req.timestamp.isoformat(),
    }
    coro_factory = lambda: websocket_manager.broadcast_event("permission_requested", event_data)

    # Case 1: running loop in THIS thread → schedule on it
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro_factory())
        return
    except RuntimeError:
        pass

    # Case 2: main loop running on another thread → thread-safe schedule
    try:
        from shail.orchestration.graph import _get_main_loop
        main_loop = _get_main_loop()
        if main_loop is not None and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro_factory(), main_loop)
            return
    except Exception as exc:
        logger.debug("Permission broadcast threadsafe schedule failed: %s", exc)

    # Case 3: no loop anywhere — log and drop. WebSocket delivery is best-effort.
    logger.debug("Permission broadcast skipped — no event loop available for task=%s",
                 permission_req.task_id)


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
        
        logger.debug("Permission request created task_id=%s tool=%s", task_id, tool_name)

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
        
        # Broadcast WebSocket notification for real-time UI updates
        _broadcast_permission_request(permission_req)

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

