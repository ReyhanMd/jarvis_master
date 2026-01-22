"""
Tool execution node using LangGraph's prebuilt ToolNode.
"""

from typing import Dict, Any, List
from shail.orchestration.langgraph_integration import get_tool_node, get_tools_condition


class ToolExecutionNode:
    def __init__(self, tools: List[Any]):
        ToolNode = get_tool_node()
        self.tools_condition = get_tools_condition()
        self.node = ToolNode(tools)

    def __call__(self, state: Dict[str, Any]):
        return self.node(state)
