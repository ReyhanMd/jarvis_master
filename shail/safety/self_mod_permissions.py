"""Self-modification permissions and safety."""

import logging
from typing import List, Set, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


# Protected files that should never be modified without explicit approval
PROTECTED_FILES: Set[str] = {
    "shail/core/router.py",
    "shail/safety/permission_manager.py",
    "shail/safety/self_mod_permissions.py",
    "apps/shail/settings.py",
    "shail/orchestration/master_planner.py",
}


class SelfModPermissions:
    """
    Manages permissions for self-modification operations.
    
    Provides:
    - Protected files list
    - Approval workflow
    - Safety checks
    """
    
    def __init__(self):
        """Initialize self-modification permissions."""
        self.protected_files = set(PROTECTED_FILES)
        logger.info(f"Initialized SelfModPermissions with {len(self.protected_files)} protected files")
    
    def is_protected(self, file_path: str) -> bool:
        """
        Check if a file is protected.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file is protected
        """
        # Normalize path
        path = Path(file_path)
        normalized = str(path).replace("\\", "/")
        
        # Check exact matches
        if normalized in self.protected_files:
            return True
        
        # Check if any protected file is a prefix
        for protected in self.protected_files:
            if normalized.startswith(protected):
                return True
        
        return False
    
    def requires_approval(self, file_path: str, operation: str = "write") -> bool:
        """
        Check if an operation requires approval.
        
        Args:
            file_path: Path to the file
            operation: Operation type ("write", "delete", etc.)
            
        Returns:
            True if approval is required
        """
        if self.is_protected(file_path):
            return True
        
        # Additional checks could go here
        # e.g., files in certain directories, files with certain patterns
        
        return False
    
    def get_approval_info(self, file_path: str, operation: str = "write") -> Dict[str, Any]:
        """
        Get information needed for approval workflow.
        
        Args:
            file_path: Path to the file
            operation: Operation type
            
        Returns:
            Dictionary with approval information
        """
        return {
            "file_path": file_path,
            "operation": operation,
            "is_protected": self.is_protected(file_path),
            "requires_approval": self.requires_approval(file_path, operation),
            "warning": "This file is protected and requires explicit approval" if self.is_protected(file_path) else None,
        }
    
    def add_protected_file(self, file_path: str):
        """
        Add a file to the protected list.
        
        Args:
            file_path: Path to protect
        """
        self.protected_files.add(file_path)
        logger.info(f"Added protected file: {file_path}")
    
    def remove_protected_file(self, file_path: str):
        """
        Remove a file from the protected list.
        
        Args:
            file_path: Path to unprotect
        """
        self.protected_files.discard(file_path)
        logger.info(f"Removed protected file: {file_path}")
    
    def list_protected_files(self) -> List[str]:
        """
        List all protected files.
        
        Returns:
            List of protected file paths
        """
        return sorted(list(self.protected_files))
