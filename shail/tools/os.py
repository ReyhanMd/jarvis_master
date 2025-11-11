import subprocess
import shlex
from langchain_core.tools import tool
from shail.safety.exceptions import PermissionRequired

# Thread-local or context variable for current task_id (for permission checks)
# For MVP, we'll use a simple approach: tools will check via a different mechanism
# The executor will handle approved context

# Safe commands that don't require permission (read-only, informational)
SAFE_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "grep", "find", "which",
    "echo", "date", "whoami", "uname", "df", "du", "wc", "sort",
    "tree", "stat", "file", "diff", "less", "more", "type"
}


def _is_safe_command(command: str) -> bool:
    """
    Determine if a command is safe to execute without permission.
    
    A command is considered safe if:
    1. It's a read-only/informational command from the safe list
    2. It doesn't contain dangerous operators (&&, ||, |, >, >>, <, etc.)
    3. It's not a deletion/modification command
    
    Args:
        command: Shell command to check
        
    Returns:
        True if safe, False if requires permission
    """
    # Check for dangerous operators
    dangerous_ops = ["&&", "||", "|", ">", ">>", "<", ";", "`", "$("]
    if any(op in command for op in dangerous_ops):
        return False
    
    # Extract the base command (first word)
    try:
        parts = shlex.split(command)
        if not parts:
            return False
        base_cmd = parts[0].lower()
        
        # Check if it's in the safe list
        if base_cmd in SAFE_COMMANDS:
            return True
        
        # Explicitly block dangerous commands
        dangerous_cmds = ["rm", "rmdir", "del", "delete", "mv", "cp", "chmod", 
                         "chown", "sudo", "su", "kill", "killall", "shutdown",
                         "reboot", "format", "dd", "mkfs", "fdisk"]
        if base_cmd in dangerous_cmds:
            return False
            
        # If not in safe list and not explicitly dangerous, require permission
        return False
    except Exception:
        # If we can't parse it, err on the side of caution
        return False


@tool
def open_app(app_name: str) -> str:
    """Open a macOS application by name (e.g., 'Calculator', 'Terminal', 'Safari').
    
    Args:
        app_name: Name of the application to open
        
    Returns:
        Status message
        
    Raises:
        PermissionRequired: Always requires user approval for security
    """
    raise PermissionRequired(
        tool_name="open_app",
        args={"app_name": app_name},
        rationale=f"Opening application: {app_name}"
    )


@tool
def close_app(app_name: str) -> str:
    """Close a macOS application by name.
    
    Args:
        app_name: Name of the application to close
        
    Returns:
        Status message
        
    Raises:
        PermissionRequired: Always requires user approval for security
    """
    raise PermissionRequired(
        tool_name="close_app",
        args={"app_name": app_name},
        rationale=f"Closing application: {app_name}"
    )


@tool
def run_command(command: str, working_dir: str = ".") -> str:
    """Run a shell command in the workspace directory.
    
    Safe read-only commands (like 'ls', 'pwd', 'cat') execute immediately.
    All other commands require explicit user approval.
    
    Args:
        command: Shell command to execute
        working_dir: Relative directory from workspace root (default: root)
        
    Returns:
        Command output or error message
        
    Raises:
        PermissionRequired: If command is not in the safe list
    """
    # Check if command is safe
    if not _is_safe_command(command):
        raise PermissionRequired(
            tool_name="run_command",
            args={"command": command, "working_dir": working_dir},
            rationale=f"Executing shell command: {command}"
        )
    
    # Safe command - execute immediately
    try:
        import os
        from shail.tools.files import BASE_DIR, _resolve_path
        wd = _resolve_path(working_dir) if working_dir != "." else BASE_DIR
        result = subprocess.run(
            command,
            shell=True,
            cwd=wd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout or "Command executed successfully"
        return f"Command failed: {result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"
    except Exception as e:
        return f"Error running command: {str(e)}"


# Approved execution functions (bypass permission checks)

def _execute_run_command_approved(command: str, working_dir: str = ".") -> str:
    """Execute run_command without permission check (for approved contexts)."""
    try:
        import os
        from shail.tools.files import BASE_DIR, _resolve_path
        wd = _resolve_path(working_dir) if working_dir != "." else BASE_DIR
        result = subprocess.run(
            command,
            shell=True,
            cwd=wd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout or "Command executed successfully"
        return f"Command failed: {result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"
    except Exception as e:
        return f"Error running command: {str(e)}"


def _execute_open_app_approved(app_name: str) -> str:
    """Execute open_app without permission check (for approved contexts)."""
    try:
        subprocess.run(["open", "-a", app_name], check=True, capture_output=True, text=True)
        return f"Opened {app_name}."
    except subprocess.CalledProcessError as e:
        return f"Error opening '{app_name}': {e.stderr or e}"


def _execute_close_app_approved(app_name: str) -> str:
    """Execute close_app without permission check (for approved contexts)."""
    try:
        subprocess.run(["osascript", "-e", f'tell application "{app_name}" to quit'], check=True, capture_output=True, text=True)
        return f"Closed {app_name}."
    except subprocess.CalledProcessError as e:
        return f"Error closing '{app_name}': {e.stderr or e}"


