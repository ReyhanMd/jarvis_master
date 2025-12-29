"""
WebSocket server for real-time LangGraph state synchronization

Provides /ws/brain endpoint for Swift UI to receive real-time state updates.
"""

import asyncio
import json
import logging
from typing import Dict, Set, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

logger = logging.getLogger(__name__)


class BrainWebSocketManager:
    """
    Manages WebSocket connections for LangGraph state broadcasting.
    """
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.state_history: list = []  # Keep last N states for new connections
        self.max_history = 100
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"🔌 WebSocket client connected. Total: {len(self.active_connections)}")
        
        # Send current state history to new client
        if self.state_history:
            await websocket.send_json({
                "type": "state_history",
                "states": self.state_history[-10:]  # Last 10 states
            })
    
    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket"""
        self.active_connections.discard(websocket)
        logger.info(f"🔌 WebSocket client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast_state(self, state: Dict[str, Any]):
        """
        Broadcast LangGraph state to all connected clients.
        
        Args:
            state: LangGraph state dictionary with nodes, edges, current_node, etc.
        """
        # Add to history
        self.state_history.append(state)
        if len(self.state_history) > self.max_history:
            self.state_history.pop(0)
        
        # Prepare message
        import time
        message = {
            "type": "state_update",
            "timestamp": time.time(),
            "state": state
        }
        
        # Broadcast to all connections
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.add(connection)
        
        # Remove disconnected connections
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """
        Broadcast a custom event to all connected clients.
        
        Args:
            event_type: Type of event (e.g., "node_started", "node_completed", "error")
            data: Event data
        """
        import time
        message = {
            "type": "event",
            "event_type": event_type,
            "timestamp": time.time(),
            "data": data
        }
        
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send event to client: {e}")
                disconnected.add(connection)
        
        for conn in disconnected:
            self.disconnect(conn)


# Global WebSocket manager instance
websocket_manager = BrainWebSocketManager()


async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint handler for /ws/brain
    
    Clients connect to receive real-time LangGraph state updates.
    """
    await websocket_manager.connect(websocket)
    
    try:
        while True:
            # Wait for messages from client (for ping/pong or commands)
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                message_type = message.get("type")
                
                if message_type == "ping":
                    # Respond to ping
                    await websocket.send_json({"type": "pong"})
                elif message_type == "subscribe":
                    # Client wants to subscribe to specific state updates
                    # For now, all clients receive all updates
                    await websocket.send_json({
                        "type": "subscribed",
                        "message": "Subscribed to all state updates"
                    })
                else:
                    logger.debug(f"Received unknown message type: {message_type}")
                    
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {data}")
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        websocket_manager.disconnect(websocket)

