"""
Custom exceptions for permission and safety controls.
"""


class PermissionRequired(Exception):
    """
    Raised when a tool requires explicit user approval before execution.
    
    This exception should be raised by tools that perform potentially dangerous
    operations (file deletion, shell commands, system modifications, etc.).
    """
    
    def __init__(self, tool_name: str, args: dict, rationale: str):
        """
        Args:
            tool_name: Name of the tool requiring permission (e.g., "run_command")
            args: Dictionary of arguments that will be passed to the tool
            rationale: Human-readable explanation of why this tool is being called
        """
        self.tool_name = tool_name
        self.args = args
        self.rationale = rationale
        super().__init__(f"Permission required for {tool_name}: {rationale}")


class PermissionDenied(Exception):
    """
    Raised when a user denies a permission request.
    """
    
    def __init__(self, task_id: str, tool_name: str):
        self.task_id = task_id
        self.tool_name = tool_name
        super().__init__(f"Permission denied for {tool_name} in task {task_id}")


class SafetyViolation(Exception):
    """
    Raised when a safety check detects a potential security violation.
    """
    
    def __init__(self, message: str, violation_type: str):
        self.violation_type = violation_type
        super().__init__(f"Safety violation ({violation_type}): {message}")

