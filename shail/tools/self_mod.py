"""Self-modification tools for SHAIL.

This module allows SHAIL to read and modify its own code.
"""

import logging
import shutil
import difflib
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def read_shail_code(file_path: str) -> Dict[str, Any]:
    """
    Read SHAIL's own source code.
    
    Args:
        file_path: Path to the file (relative to project root or absolute)
        
    Returns:
        Dictionary with file content and metadata
    """
    path = Path(file_path)
    
    # If relative path, try to resolve from shail directory
    if not path.is_absolute():
        current_file = Path(__file__)
        shail_dir = current_file.parent.parent
        path = shail_dir / file_path
    
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "file_path": str(path),
            "content": content,
            "lines": len(content.splitlines()),
            "size": len(content),
            "read_at": datetime.now().isoformat(),
        }
    
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return {"error": str(e)}


def backup_file(file_path: str, backup_dir: Optional[str] = None) -> str:
    """
    Create a backup of a file before modification.
    
    Args:
        file_path: Path to the file to backup
        backup_dir: Optional backup directory (defaults to .shail_backups/)
        
    Returns:
        Path to the backup file
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if backup_dir is None:
        backup_dir = Path.cwd() / ".shail_backups"
    else:
        backup_dir = Path(backup_dir)
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Create backup with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{path.stem}_{timestamp}{path.suffix}"
    backup_path = backup_dir / backup_name
    
    shutil.copy2(path, backup_path)
    logger.info(f"Created backup: {backup_path}")
    
    return str(backup_path)


def get_code_diff(old_content: str, new_content: str) -> Dict[str, Any]:
    """
    Generate a diff between old and new code.
    
    Args:
        old_content: Original code content
        new_content: Modified code content
        
    Returns:
        Dictionary with diff information
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        lineterm='',
    ))
    
    return {
        "diff": ''.join(diff),
        "old_lines": len(old_lines),
        "new_lines": len(new_lines),
        "changes": len([line for line in diff if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))]),
    }


def write_shail_code(
    file_path: str,
    content: str,
    create_backup: bool = True,
    require_approval: bool = True,
) -> Dict[str, Any]:
    """
    Write to SHAIL's own source code (with safety checks).
    
    Args:
        file_path: Path to the file
        content: New content to write
        create_backup: Whether to create a backup first
        require_approval: Whether approval is required (for integration with approval system)
        
    Returns:
        Dictionary with write result
    """
    path = Path(file_path)
    
    # If relative path, try to resolve from shail directory
    if not path.is_absolute():
        current_file = Path(__file__)
        shail_dir = current_file.parent.parent
        path = shail_dir / file_path
    
    result = {
        "file_path": str(path),
        "backup_path": None,
        "diff": None,
        "written": False,
        "requires_approval": require_approval,
    }
    
    # Read existing content for diff
    old_content = ""
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            old_content = f.read()
        
        # Generate diff
        result["diff"] = get_code_diff(old_content, content)
        
        # Create backup if requested
        if create_backup:
            backup_path = backup_file(str(path))
            result["backup_path"] = backup_path
    
    # If approval required, don't write yet
    if require_approval:
        result["message"] = "Approval required before writing"
        return result
    
    # Write the file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        result["written"] = True
        result["message"] = "File written successfully"
        logger.info(f"Wrote file: {path}")
    
    except Exception as e:
        logger.error(f"Error writing file {file_path}: {e}")
        result["error"] = str(e)
    
    return result
