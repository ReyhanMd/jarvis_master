"""
WebSocket server for real-time LangGraph state synchronization

Provides /ws/brain endpoint for Swift UI to receive real-time state updates.
"""

import asyncio
import json
import logging
import os
from typing import Dict, Set, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


def ensure_log_dir():
    """Ensure .cursor directory exists for debug logs"""
    log_dir = os.path.join(os.path.expanduser("~"), "jarvis_master", ".cursor")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "debug.log")


def safe_log_write(log_entry: dict):
    """Safely write log entry without raising exceptions"""
    try:
        log_path = ensure_log_dir()
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
            f.flush()
    except Exception as e:
        logger.debug(f"Failed to write debug log: {e}")
        # Don't raise - logging failures shouldn't break functionality


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
        import json
        import time
        
        # Log client information before accepting
        client_host = websocket.client.host if websocket.client else "unknown"
        client_port = websocket.client.port if websocket.client else "unknown"
        logger.info(f"📡 WebSocket connection attempt from {client_host}:{client_port}")
        
        # #region agent log
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:connect","message":"WebSocket connection attempt","data":{"client_host":client_host,"client_port":client_port},"timestamp":time.time()})
        # #endregion
        
        try:
            # Accept the WebSocket handshake
            await websocket.accept()
            
            # Add to active connections
            self.active_connections.add(websocket)
            
            logger.info(f"🔌 WebSocket client connected from {client_host}:{client_port}. Total: {len(self.active_connections)}")
            
            # #region agent log
            safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:connect","message":"WebSocket client connected","data":{"total_connections":len(self.active_connections),"client_host":client_host,"client_port":client_port},"timestamp":time.time()})
            # #endregion
            
            # Send current state history to new client
            if self.state_history:
                await websocket.send_json({
                    "type": "state_history",
                    "states": self.state_history[-10:]  # Last 10 states
                })
                
        except Exception as e:
            # Log handshake failure
            logger.error(f"❌ WebSocket handshake failed for {client_host}:{client_port}: {e}", exc_info=True)
            
            # #region agent log
            safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:connect","message":"WebSocket handshake failed","data":{"client_host":client_host,"client_port":client_port,"error":str(e)},"timestamp":time.time()})
            # #endregion
            
            # Re-raise to let caller handle it
            raise
    
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
        import json
        # #region agent log
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"C","location":"websocket_server.py:broadcast_event","message":"Broadcasting event","data":{"event_type":event_type,"connections":len(self.active_connections)},"timestamp":time.time()})
        # #endregion
        message = {
            "type": "event",
            "event_type": event_type,
            "timestamp": time.time(),
            "data": data
        }
        
        disconnected = set()
        sent_count = 0
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                sent_count += 1
                # #region agent log
                safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"C","location":"websocket_server.py:broadcast_event","message":"Event sent to client","data":{"event_type":event_type},"timestamp":time.time()})
                # #endregion
            except Exception as e:
                logger.warning(f"Failed to send event to client: {e}")
                # #region agent log
                safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"C","location":"websocket_server.py:broadcast_event","message":"Failed to send event","data":{"error":str(e)},"timestamp":time.time()})
                # #endregion
                disconnected.add(connection)
        
        # #region agent log
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"C","location":"websocket_server.py:broadcast_event","message":"Broadcast complete","data":{"sent":sent_count,"disconnected":len(disconnected)},"timestamp":time.time()})
        # #endregion
        
        for conn in disconnected:
            self.disconnect(conn)


# Global WebSocket manager instance
websocket_manager = BrainWebSocketManager()


async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint handler for /ws/brain
    
    Clients connect to receive real-time LangGraph state updates.
    """
    try:
        # #region agent log
        import time
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:websocket_endpoint","message":"WebSocket endpoint called","data":{},"timestamp":time.time()})
        # #endregion
        logger.info("WebSocket connection attempt received")
        
        await websocket_manager.connect(websocket)
        
        # #region agent log
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:websocket_endpoint","message":"WebSocket accepted, entering message loop","data":{},"timestamp":time.time()})
        # #endregion
        
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
        # #region agent log
        import time
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:websocket_endpoint","message":"WebSocket disconnected","data":{},"timestamp":time.time()})
        # #endregion
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        # #region agent log
        import time
        safe_log_write({"sessionId":"debug-session","runId":"test-permission-ws","hypothesisId":"A","location":"websocket_server.py:websocket_endpoint","message":"WebSocket error","data":{"error":str(e)},"timestamp":time.time()})
        # #endregion
        try:
            websocket_manager.disconnect(websocket)
        except:
            pass

