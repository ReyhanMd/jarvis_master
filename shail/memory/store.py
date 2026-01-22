import sqlite3
import os
import json
from typing import List, Tuple, Optional, Dict, Any
from apps.shail.settings import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS convo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _conn():
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.sqlite_path), exist_ok=True)
    cx = sqlite3.connect(settings.sqlite_path)
    # Use executescript() to run multiple CREATE TABLE statements
    cx.executescript(SCHEMA)
    return cx


def append_message(role: str, text: str) -> None:
    cx = _conn()
    with cx:
        cx.execute("INSERT INTO convo(role, text) VALUES(?, ?)", (role, text))
    cx.close()


def last_messages(limit: int = 20) -> List[Tuple[str, str]]:
    cx = _conn()
    cur = cx.execute("SELECT role, text FROM convo ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    cx.close()
    return rows[::-1]


def get_chat_history(limit: int = 200) -> List[Dict[str, Any]]:
    """
    Fetch chat history ordered by id ascending.
    """
    cx = _conn()
    cur = cx.execute(
        "SELECT id, role, text, ts FROM convo ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    cx.close()
    history = []
    for row in rows:
        msg_id, role, text, ts = row
        history.append(
            {
                "id": str(msg_id),
                "role": role,
                "text": text,
                "timestamp": ts,
            }
        )
    return history


# Task store functions for async execution

def create_task(task_id: str, request: Dict[str, Any]) -> None:
    """
    Store a new task in the database.
    
    Args:
        task_id: Unique task identifier
        request: Task request data (will be JSON-serialized)
    """
    cx = _conn()
    try:
        cx.execute(
            """INSERT INTO tasks (task_id, request_json, status)
               VALUES (?, ?, ?)""",
            (task_id, json.dumps(request), "pending")
        )
        cx.commit()
    finally:
        cx.close()


def update_task_status(task_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> None:
    """
    Update task status and optionally store result.
    
    Args:
        task_id: Task identifier
        status: New status (e.g., "running", "completed", "failed")
        result: Optional result data (will be JSON-serialized)
    """
    cx = _conn()
    try:
        result_json = json.dumps(result) if result else None
        cx.execute(
            """UPDATE tasks 
               SET status = ?, result_json = ?, updated_at = CURRENT_TIMESTAMP
               WHERE task_id = ?""",
            (status, result_json, task_id)
        )
        cx.commit()
    finally:
        cx.close()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a task from the database.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Dict with task data (task_id, request_json, status, result_json, timestamps)
        or None if not found
    """
    cx = _conn()
    try:
        cur = cx.execute(
            """SELECT task_id, request_json, status, result_json, created_at, updated_at
               FROM tasks WHERE task_id = ?""",
            (task_id,)
        )
        row = cur.fetchone()
        if row:
            task_id_db, request_json, status, result_json, created_at, updated_at = row
            return {
                "task_id": task_id_db,
                "request": json.loads(request_json),
                "status": status,
                "result": json.loads(result_json) if result_json else None,
                "created_at": created_at,
                "updated_at": updated_at
            }
        return None
    finally:
        cx.close()


def get_all_tasks(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Retrieve all tasks from the database, ordered by most recent first.
    
    Args:
        limit: Maximum number of tasks to return
        offset: Number of tasks to skip (for pagination)
        
    Returns:
        List of task dictionaries
    """
    cx = _conn()
    try:
        cur = cx.execute(
            """SELECT task_id, request_json, status, result_json, created_at, updated_at
               FROM tasks
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        )
        rows = cur.fetchall()
        tasks = []
        for row in rows:
            task_id_db, request_json, status, result_json, created_at, updated_at = row
            tasks.append({
                "task_id": task_id_db,
                "request": json.loads(request_json),
                "status": status,
                "result": json.loads(result_json) if result_json else None,
                "created_at": created_at,
                "updated_at": updated_at
            })
        return tasks
    finally:
        cx.close()


