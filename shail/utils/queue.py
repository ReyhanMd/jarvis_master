"""
Task Queue - Redis-based queue for asynchronous task execution.

Provides:
- Enqueue tasks for background processing
- Dequeue tasks for worker consumption
- Simple, reliable task distribution
"""

import json
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False
from typing import Optional, Dict, Any
from apps.shail.settings import get_settings


class TaskQueue:
    """
    Redis-based task queue for asynchronous task execution.
    
    Uses Redis LIST (LPUSH/RPOP) for simple FIFO queue semantics.
    Tasks are stored as JSON strings.
    """
    
    def __init__(self, redis_url: str = None, queue_name: str = None):
        """
        Initialize the task queue.
        
        Args:
            redis_url: Redis connection URL (defaults to settings)
            queue_name: Queue name (defaults to settings)
        """
        if not REDIS_AVAILABLE:
            raise ImportError("redis is not installed. Install with: pip install redis")
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.queue_name = queue_name or settings.task_queue_name
        
        # Initialize Redis connection (will connect on first use)
        self._redis_client: Optional[Any] = None
    
    @property
    def redis(self) -> Any:
        """Lazy initialization of Redis client."""
        if self._redis_client is None:
            try:
                self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
                # Test connection
                self._redis_client.ping()
            except redis.ConnectionError as e:
                raise ConnectionError(
                    f"Failed to connect to Redis at {self.redis_url}. "
                    f"Make sure Redis is running. Error: {e}"
                )
        return self._redis_client
    
    def enqueue(self, task_id: str, request: Dict[str, Any]) -> bool:
        """
        Enqueue a task for processing.
        
        Args:
            task_id: Unique task identifier
            request: Task request data (will be JSON-serialized)
            
        Returns:
            True if successful
        """
        try:
            task_data = {
                "task_id": task_id,
                "request": request
            }
            self.redis.lpush(self.queue_name, json.dumps(task_data))
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to enqueue task {task_id}: {e}")
    
    def dequeue(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Dequeue a task from the queue (blocks until task available or timeout).
        
        Args:
            timeout: Blocking timeout in seconds (default: 5)
            
        Returns:
            Task data dict with 'task_id' and 'request', or None if timeout
        """
        try:
            # BRPOP blocks until a task is available or timeout expires
            result = self.redis.brpop(self.queue_name, timeout=timeout)
            if result:
                # result is a tuple: (queue_name, task_json_string)
                task_json = result[1]
                return json.loads(task_json)
            return None
        except redis.ConnectionError as e:
            raise ConnectionError(f"Redis connection lost: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid task data in queue: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to dequeue task: {e}")
    
    def queue_length(self) -> int:
        """
        Get the current length of the queue.
        
        Returns:
            Number of tasks in queue
        """
        try:
            return self.redis.llen(self.queue_name)
        except Exception as e:
            raise RuntimeError(f"Failed to get queue length: {e}")
    
    def clear(self) -> int:
        """
        Clear all tasks from the queue (use with caution!).
        
        Returns:
            Number of tasks removed
        """
        try:
            return self.redis.delete(self.queue_name)
        except Exception as e:
            raise RuntimeError(f"Failed to clear queue: {e}")

