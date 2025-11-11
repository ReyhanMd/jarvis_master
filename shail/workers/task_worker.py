"""
Task Worker - Background process that polls Redis queue and executes tasks.

This worker:
1. Polls the Redis queue for new tasks
2. Executes tasks using ShailCoreRouter
3. Handles permission requests (updates status to AWAITING_APPROVAL)
4. Stores results in the task database
"""

import sys
import os
import signal
import time
from typing import Optional

# Ensure project root is on sys.path BEFORE any imports
# task_worker.py is at: shail/workers/task_worker.py
# So we need to go up 2 levels: .. -> shail, .. -> project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# CRITICAL: Insert at the very beginning, before any imports
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Verify the path is correct
if not os.path.exists(os.path.join(PROJECT_ROOT, "shail", "__init__.py")):
    raise ImportError(
        f"Cannot find shail package. "
        f"Project root: {PROJECT_ROOT}, "
        f"Expected shail at: {os.path.join(PROJECT_ROOT, 'shail')}"
    )

from shail.utils.queue import TaskQueue
from shail.core.router import ShailCoreRouter
from shail.core.types import TaskRequest, TaskResult, TaskStatus
from shail.memory.store import create_task, update_task_status, get_task
from shail.safety.permission_manager import PermissionManager
from apps.shail.settings import get_settings


class TaskWorker:
    """
    Worker process that executes tasks from the Redis queue.
    """
    
    def __init__(self):
        self.queue = TaskQueue()
        self.router = ShailCoreRouter()
        self.running = True
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\nReceived signal {signum}, shutting down gracefully...")
        self.running = False
    
    def process_task(self, task_data: dict) -> None:
        """
        Process a single task from the queue.
        
        Args:
            task_data: Dict with 'task_id' and 'request' keys
        """
        task_id = task_data["task_id"]
        request_data = task_data["request"]
        
        print(f"[Worker] Processing task {task_id}: {request_data.get('text', '')[:50]}...")
        
        try:
            # Reconstruct TaskRequest
            request = TaskRequest(**request_data)
            
            # Update status to running
            update_task_status(task_id, "running")
            
            # Execute the task
            # Note: If task needs permission, router will return AWAITING_APPROVAL
            # If permission was already approved, it will proceed normally
            result = self.router.route(request, task_id=task_id)
            
            # Handle result status
            if result.status == TaskStatus.AWAITING_APPROVAL:
                # Task needs permission - update status and return (task stays in queue conceptually)
                update_task_status(task_id, "awaiting_approval", result.dict())
                print(f"[Worker] Task {task_id} awaiting approval for {result.permission_request.tool_name if result.permission_request else 'unknown'}")
                # Don't store as completed - user needs to approve first
                return
            
            elif result.status == TaskStatus.COMPLETED:
                # Task completed successfully
                update_task_status(task_id, "completed", result.dict())
                print(f"[Worker] Task {task_id} completed successfully")
            
            elif result.status == TaskStatus.FAILED:
                # Task failed
                update_task_status(task_id, "failed", result.dict())
                print(f"[Worker] Task {task_id} failed: {result.summary}")
            
            else:
                # Unknown status
                update_task_status(task_id, result.status.value if isinstance(result.status, TaskStatus) else result.status, result.dict())
                print(f"[Worker] Task {task_id} ended with status: {result.status}")
        
        except Exception as e:
            # Task execution error
            error_result = {
                "status": "failed",
                "summary": f"Worker error: {str(e)}",
                "error": str(e)
            }
            update_task_status(task_id, "failed", error_result)
            print(f"[Worker] Error processing task {task_id}: {e}", file=sys.stderr)
    
    def run(self, poll_timeout: int = 5):
        """
        Main worker loop - polls queue and processes tasks.
        
        Args:
            poll_timeout: Seconds to block waiting for tasks (default: 5)
        """
        print(f"[Worker] Starting task worker (polling queue '{self.queue.queue_name}')...")
        print(f"[Worker] Poll timeout: {poll_timeout}s")
        
        while self.running:
            try:
                # Dequeue a task (blocks until available or timeout)
                task_data = self.queue.dequeue(timeout=poll_timeout)
                
                if task_data:
                    self.process_task(task_data)
                # else: timeout, loop continues
                
            except KeyboardInterrupt:
                print("\n[Worker] Keyboard interrupt received")
                self.running = False
                break
            except Exception as e:
                error_msg = str(e)
                # If it's a Redis connection error, provide helpful message (but don't spam)
                if "Connection refused" in error_msg or "Failed to connect to Redis" in error_msg:
                    # Only print this message every 10 seconds to avoid spam
                    current_time = time.time()
                    if not hasattr(self, "_last_redis_error_time") or (current_time - self._last_redis_error_time) >= 10:
                        print(
                            "[Worker] ❌ Redis is not running!\n"
                            "   Please start Redis in a separate terminal:\n"
                            "   → redis-server\n"
                            "   Or install Redis if you haven't: brew install redis",
                            file=sys.stderr
                        )
                        self._last_redis_error_time = current_time
                else:
                    print(f"[Worker] Error in worker loop: {e}", file=sys.stderr)
                # Continue running even if one task fails
                time.sleep(1)  # Brief pause before retrying
        
        print("[Worker] Worker stopped")


def main():
    """Entry point for the worker process."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Shail Task Worker")
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Poll timeout in seconds (default: 5)"
    )
    args = parser.parse_args()
    
    worker = TaskWorker()
    try:
        worker.run(poll_timeout=args.timeout)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

