"""
Exports graph factories for LangGraph Studio.
"""

from shail.orchestration.graph import LangGraphExecutor
from shail.orchestration.nodes.master_node import MasterNode
from shail.orchestration.nodes.worker_nodes import WorkerNodes
from shail.orchestration.nodes.permission_node import PermissionNode
from shail.orchestration.nodes.recovery_node import RecoveryNode


def orchestration_graph(agent, task_id: str = None):
    """
    Build a LangGraphExecutor-backed graph for Studio visualization.
    """
    executor = LangGraphExecutor(agent, task_id=task_id, persistent=True)
    return executor.build_graph()


def nodes_catalog():
    """
    Return a catalog of Shail-specific node builders for reuse.
    """
    return {
        "master": MasterNode,
        "workers": WorkerNodes,
        "permission": PermissionNode,
        "recovery": RecoveryNode,
    }
