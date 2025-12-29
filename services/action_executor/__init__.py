"""
Action Executor Service

Executes UI actions (click, type, etc) with safety constraints and verification.
"""

from .service import ActionExecutorService
from .models import Action, ActionResult

__all__ = ['ActionExecutorService', 'Action', 'ActionResult']

