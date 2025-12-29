"""Worker LLM system for SHAIL."""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class WorkerLLMType(str, Enum):
    """Types of worker LLMs."""
    GEMINI = "gemini"
    CHATGPT = "chatgpt"


class WorkerLLMManager:
    """
    Manages worker LLMs for task distribution.
    
    The master LLM (Kimi-K2) distributes tasks to worker LLMs
    (Gemini, ChatGPT) for parallel execution.
    """
    
    def __init__(self):
        """Initialize the worker LLM manager."""
        self.workers: Dict[str, Any] = {}
        logger.info("Initialized WorkerLLMManager")
    
    def register_worker(self, worker_type: WorkerLLMType, worker_instance: Any):
        """
        Register a worker LLM.
        
        Args:
            worker_type: Type of worker (GEMINI, CHATGPT)
            worker_instance: Worker LLM instance
        """
        self.workers[worker_type.value] = worker_instance
        logger.info(f"Registered worker LLM: {worker_type.value}")
    
    def distribute_task(
        self,
        task: str,
        worker_type: Optional[WorkerLLMType] = None,
    ) -> Dict[str, Any]:
        """
        Distribute a task to a worker LLM.
        
        Args:
            task: Task description
            worker_type: Optional specific worker type, otherwise auto-select
            
        Returns:
            Dictionary with task result
        """
        if worker_type:
            worker = self.workers.get(worker_type.value)
            if not worker:
                return {"error": f"Worker {worker_type.value} not registered"}
        else:
            # Auto-select first available worker
            if not self.workers:
                return {"error": "No worker LLMs registered"}
            worker = list(self.workers.values())[0]
        
        # Execute task on worker
        try:
            result = worker.execute(task)
            return {
                "success": True,
                "result": result,
                "worker": worker_type.value if worker_type else "auto",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def list_workers(self) -> List[str]:
        """
        List registered worker LLMs.
        
        Returns:
            List of worker type names
        """
        return list(self.workers.keys())
