"""Code introspection module for SHAIL.

This module allows SHAIL to understand its own codebase structure,
dependencies, and architecture.
"""

import ast
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
import importlib.util

logger = logging.getLogger(__name__)


def list_shail_modules(directory: Optional[str] = None) -> List[str]:
    """
    List all Python modules in the shail directory.
    
    Args:
        directory: Optional directory path (defaults to shail/)
        
    Returns:
        List of module paths
    """
    if directory is None:
        # Find shail directory
        current_file = Path(__file__)
        shail_dir = current_file.parent.parent
    else:
        shail_dir = Path(directory)
    
    modules = []
    for py_file in shail_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel_path = py_file.relative_to(shail_dir.parent)
        module_path = str(rel_path.with_suffix("")).replace(os.sep, ".")
        modules.append(module_path)
    
    return sorted(modules)


def get_agent_structure(agent_name: str) -> Dict[str, Any]:
    """
    Extract structure of an agent (class structure, methods, tools).
    
    Args:
        agent_name: Name of the agent (e.g., "code", "friend")
        
    Returns:
        Dictionary with agent structure information
    """
    try:
        # Try to import the agent
        agent_module = f"shail.agents.{agent_name}"
        spec = importlib.util.find_spec(agent_module)
        
        if spec is None or spec.loader is None:
            return {"error": f"Agent {agent_name} not found"}
        
        # Read and parse the file
        file_path = spec.origin
        if file_path is None:
            return {"error": f"Could not find file for {agent_name}"}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        structure = {
            "agent_name": agent_name,
            "file_path": file_path,
            "classes": [],
            "functions": [],
            "imports": [],
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                structure["classes"].append({
                    "name": node.name,
                    "methods": methods,
                    "bases": [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
                })
            elif isinstance(node, ast.FunctionDef) and not any(isinstance(n, ast.ClassDef) for n in ast.walk(tree) if hasattr(n, "body") and node in getattr(n, "body", [])):
                structure["functions"].append({
                    "name": node.name,
                    "args": [arg.arg for arg in node.args.args],
                })
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    structure["imports"].extend([alias.name for alias in node.names])
                else:
                    structure["imports"].append(node.module or "")
        
        return structure
    
    except Exception as e:
        logger.error(f"Error extracting agent structure: {e}")
        return {"error": str(e)}


def find_code_pattern(pattern: str, directory: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for code patterns in the codebase.
    
    Args:
        pattern: Pattern to search for (simple string search for now)
        directory: Optional directory to search
        
    Returns:
        List of matches with file and line information
    """
    if directory is None:
        current_file = Path(__file__)
        search_dir = current_file.parent.parent
    else:
        search_dir = Path(directory)
    
    matches = []
    for py_file in search_dir.rglob("*.py"):
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if pattern.lower() in line.lower():
                        matches.append({
                            "file": str(py_file),
                            "line": line_num,
                            "content": line.strip(),
                        })
        except Exception as e:
            logger.warning(f"Error reading {py_file}: {e}")
    
    return matches


def get_dependencies(module_path: str) -> Dict[str, Any]:
    """
    Analyze imports and dependencies for a module.
    
    Args:
        module_path: Path to the module file
        
    Returns:
        Dictionary with dependency information
    """
    path = Path(module_path)
    if not path.exists():
        return {"error": f"File not found: {module_path}"}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        dependencies = {
            "module": str(path),
            "imports": [],
            "from_imports": [],
            "internal_deps": [],
            "external_deps": [],
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dep = alias.name
                    dependencies["imports"].append(dep)
                    if dep.startswith("shail."):
                        dependencies["internal_deps"].append(dep)
                    else:
                        dependencies["external_deps"].append(dep)
            
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module:
                    dependencies["from_imports"].append(module)
                    if module.startswith("shail."):
                        dependencies["internal_deps"].append(module)
                    else:
                        dependencies["external_deps"].append(module)
        
        # Remove duplicates
        dependencies["internal_deps"] = list(set(dependencies["internal_deps"]))
        dependencies["external_deps"] = list(set(dependencies["external_deps"]))
        
        return dependencies
    
    except Exception as e:
        logger.error(f"Error analyzing dependencies: {e}")
        return {"error": str(e)}


def analyze_architecture(directory: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze the overall architecture of the SHAIL codebase.
    
    Args:
        directory: Optional directory to analyze
        
    Returns:
        Dictionary with architecture information
    """
    if directory is None:
        current_file = Path(__file__)
        shail_dir = current_file.parent.parent
    else:
        shail_dir = Path(directory)
    
    architecture = {
        "modules": [],
        "agents": [],
        "tools": [],
        "integrations": [],
    }
    
    # Find agents
    agents_dir = shail_dir / "agents"
    if agents_dir.exists():
        for agent_file in agents_dir.glob("*.py"):
            if agent_file.name != "__init__.py":
                agent_name = agent_file.stem
                architecture["agents"].append(agent_name)
    
    # Find tools
    tools_dir = shail_dir / "tools"
    if tools_dir.exists():
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name != "__init__.py":
                tool_name = tool_file.stem
                architecture["tools"].append(tool_name)
    
    # Find integrations
    integrations_dir = shail_dir / "integrations"
    if integrations_dir.exists():
        for integration_dir in integrations_dir.iterdir():
            if integration_dir.is_dir():
                architecture["integrations"].append(integration_dir.name)
    
    # List all modules
    architecture["modules"] = list_shail_modules(str(shail_dir))
    
    return architecture
