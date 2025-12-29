"""
Thread-local context for permission tracking.

This module provides thread-local storage for the current task_id,
allowing tools to check if they're in an approved execution context.
"""

import threading

_context = threading.local()


def set_current_task_id(task_id: str) -> None:
    """Set the current task ID for this thread."""
    _context.task_id = task_id


def get_current_task_id() -> str | None:
    """Get the current task ID for this thread, or None if not set."""
    return getattr(_context, 'task_id', None)


def clear_current_task_id() -> None:
    """Clear the current task ID for this thread."""
    if hasattr(_context, 'task_id'):
        delattr(_context, 'task_id')

