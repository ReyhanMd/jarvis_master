"""
Agent Registry - Describes capabilities and purposes of all available agents.

This registry is used by the Master Planner LLM to intelligently route requests
to the most appropriate agent based on their capabilities.
"""

from typing import Dict, List


AGENT_CAPABILITIES: Dict[str, Dict[str, any]] = {
    "code": {
        "name": "CodeAgent",
        "description": "Builds websites, applications, APIs, and software projects using modern frameworks and tools.",
        "capabilities": [
            "code generation in Python, JavaScript, TypeScript, and other languages",
            "web application development (Next.js, React, Flask, FastAPI, etc.)",
            "file operations (read, write, create, delete files and directories)",
            "running shell commands and scripts",
            "managing dependencies and project scaffolding",
            "opening and closing desktop applications",
            "building REST APIs and backend services",
            "creating project structures and boilerplate code"
        ],
        "example_requests": [
            "create a Next.js app",
            "build a Flask API",
            "write a Python script to process data",
            "scaffold a new project",
            "run npm install",
            "open VS Code"
        ],
        "keywords": ["code", "build", "website", "app", "api", "next.js", "python", "flask", "react", "programming", "script", "develop"]
    },
    
    "bio": {
        "name": "BioAgent",
        "description": "Handles biological and bioinformatics tasks including protein design, gene editing, molecular modeling, and biological simulations.",
        "capabilities": [
            "protein structure prediction and design",
            "CRISPR gene editing design and analysis",
            "drug discovery and molecular docking",
            "DNA/RNA sequence analysis",
            "phylogenetic analysis",
            "biological pathway modeling",
            "molecular dynamics simulations"
        ],
        "example_requests": [
            "design a protein sequence",
            "analyze a DNA sequence",
            "design a CRISPR guide RNA",
            "predict protein folding",
            "find drug targets",
            "simulate molecular interactions"
        ],
        "keywords": ["protein", "crispr", "gene", "drug", "fold", "sequence", "dna", "rna", "molecular", "biology", "bioinformatics"]
    },
    
    "robo": {
        "name": "RoboAgent",
        "description": "Handles robotics, mechanical design, CAD, and robotic system control.",
        "capabilities": [
            "CAD design and modeling (SolidWorks, FreeCAD, etc.)",
            "robotic kinematics and dynamics",
            "ROS (Robot Operating System) integration",
            "mechanical system simulation",
            "robot control logic and programming",
            "CAM (Computer-Aided Manufacturing) workflows",
            "3D modeling and design"
        ],
        "example_requests": [
            "design a robot arm",
            "create a CAD model",
            "simulate robot kinematics",
            "generate ROS launch files",
            "design a drone frame",
            "create a mechanical part"
        ],
        "keywords": ["cad", "robot", "solidworks", "freecad", "ros", "kinematics", "mechanical", "drone", "robotics", "3d model"]
    },
    
    "plasma": {
        "name": "PlasmaAgent",
        "description": "Handles plasma physics, fusion simulations, fluid dynamics, and advanced physics simulations.",
        "capabilities": [
            "plasma physics simulations",
            "fusion reactor modeling",
            "computational fluid dynamics (CFD)",
            "MATLAB and Simulink simulations",
            "OpenFOAM simulations",
            "electromagnetic field simulations",
            "high-energy physics modeling"
        ],
        "example_requests": [
            "simulate plasma behavior",
            "model a fusion reactor",
            "run a CFD simulation",
            "analyze fluid flow",
            "design a plasma confinement system",
            "simulate electromagnetic fields"
        ],
        "keywords": ["plasma", "fusion", "openfoam", "simulink", "matlab", "cfd", "fluid", "physics", "simulation", "electromagnetic"]
    },
    
    "research": {
        "name": "ResearchAgent",
        "description": "Handles research tasks, literature review, data gathering, summarization, and knowledge synthesis.",
        "capabilities": [
            "literature search and review",
            "paper summarization and analysis",
            "web research and information gathering",
            "data collection and synthesis",
            "research paper writing assistance",
            "citation management",
            "knowledge extraction from documents"
        ],
        "example_requests": [
            "search for papers on machine learning",
            "summarize this research paper",
            "find information about quantum computing",
            "gather data on renewable energy",
            "write a literature review",
            "analyze research trends"
        ],
        "keywords": ["paper", "literature", "research", "summarize", "data", "review", "article", "citation", "academic", "journal"]
    },
    
    "friend": {
        "name": "FriendAgent",
        "description": "Friendly conversational AI assistant with desktop control capabilities. Perfect for hands-free computer interaction and natural conversation.",
        "capabilities": [
            "mouse control (click, move, scroll)",
            "keyboard input (typing, key presses, hotkeys)",
            "window management (focus, get position)",
            "natural conversation and assistance",
            "multi-step desktop automation",
            "hands-free computer control"
        ],
        "example_requests": [
            "click on the top right corner",
            "type hello world",
            "open Safari and click the search bar",
            "scroll down the page",
            "press cmd+c to copy",
            "focus the Terminal window",
            "help me navigate my computer"
        ],
        "keywords": ["click", "mouse", "keyboard", "type", "scroll", "window", "desktop", "control", "friend", "help", "conversation", "hands-free"]
    }
}


def get_agent_info(agent_name: str) -> Dict[str, any]:
    """
    Get information about a specific agent.
    
    Args:
        agent_name: Name of the agent (e.g., "code", "bio")
        
    Returns:
        Agent capability dictionary or empty dict if not found
    """
    return AGENT_CAPABILITIES.get(agent_name, {})


def list_all_agents() -> List[str]:
    """
    Get list of all available agent names.
    
    Returns:
        List of agent names
    """
    return list(AGENT_CAPABILITIES.keys())


def format_capabilities_for_llm() -> str:
    """
    Format agent capabilities as a readable string for LLM prompts.
    
    Returns:
        Formatted string describing all agents and their capabilities
    """
    lines = []
    lines.append("Available Agents and Their Capabilities:\n")
    lines.append("=" * 80)
    
    for agent_id, info in AGENT_CAPABILITIES.items():
        lines.append(f"\n{info['name']} (ID: {agent_id})")
        lines.append(f"  Description: {info['description']}")
        lines.append("  Capabilities:")
        for cap in info['capabilities']:
            lines.append(f"    - {cap}")
        lines.append("  Example Requests:")
        for ex in info['example_requests'][:3]:  # Show first 3 examples
            lines.append(f"    - \"{ex}\"")
    
    lines.append("\n" + "=" * 80)
    
    return "\n".join(lines)

