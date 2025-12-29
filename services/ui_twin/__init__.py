"""
UI Digital Twin Service

Maintains real-time in-memory graph of UI elements from accessibility + vision streams.
Provides temporal buffer and episodic memory for UI state tracking.
"""

from .service import UITwinService
from .models import UIElement, UISnapshot

__all__ = ['UITwinService', 'UIElement', 'UISnapshot']

