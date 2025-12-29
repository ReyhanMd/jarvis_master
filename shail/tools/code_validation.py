"""Code validation and safety for self-modification."""

import ast
import logging
import subprocess
import sys
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_python_syntax(code: str) -> Dict[str, Any]:
    """
    Validate Python syntax using ast.parse.
    
    Args:
        code: Python code to validate
        
    Returns:
        Dictionary with validation result
    """
    try:
        ast.parse(code)
        return {
            "valid": True,
            "error": None,
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "error": {
                "message": str(e),
                "line": e.lineno,
                "offset": e.offset,
            },
        }
    except Exception as e:
        return {
            "valid": False,
            "error": {
                "message": str(e),
            },
        }


def test_import(module_path: str) -> Dict[str, Any]:
    """
    Test if a module can be imported.
    
    Args:
        module_path: Path to the module file
        
    Returns:
        Dictionary with import test result
    """
    path = Path(module_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {module_path}",
        }
    
    try:
        # Try to compile the file
        with open(path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        compile(code, str(path), 'exec')
        
        return {
            "success": True,
            "error": None,
        }
    
    except SyntaxError as e:
        return {
            "success": False,
            "error": f"Syntax error: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Import error: {e}",
        }


def run_basic_tests(test_command: Optional[str] = None) -> Dict[str, Any]:
    """
    Run basic tests after modification.
    
    Args:
        test_command: Optional custom test command
        
    Returns:
        Dictionary with test results
    """
    if test_command is None:
        # Default: try to run pytest if available
        test_command = "python -m pytest tests/ -v"
    
    try:
        result = subprocess.run(
            test_command.split(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Tests timed out",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def lint_code(code: str, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Lint code using available linters.
    
    Args:
        code: Code to lint
        file_path: Optional file path for context
        
    Returns:
        Dictionary with linting results
    """
    issues = []
    
    # Try pylint
    try:
        import pylint.lint
        from io import StringIO
        
        output = StringIO()
        pylint.lint.Run(
            [file_path] if file_path else ['--from-stdin'],
            exit=False,
            stdout=output,
        )
        output_str = output.getvalue()
        if output_str:
            issues.append({
                "linter": "pylint",
                "output": output_str,
            })
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Pylint error: {e}")
    
    # Try flake8
    try:
        import flake8.main.application
        from io import StringIO
        
        app = flake8.main.application.Application()
        output = StringIO()
        app.run([file_path] if file_path else ['--stdin-display-name', '<string>'])
        # Flake8 output handling would go here
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Flake8 error: {e}")
    
    return {
        "issues": issues,
        "has_issues": len(issues) > 0,
    }
