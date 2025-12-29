"""
UI Twin Service - Real-time UI state tracking
"""

import asyncio
import json
import time
import threading
import sys
import os
import websockets
from collections import deque
from typing import Dict, List, Optional
from loguru import logger

# Handle imports for both module and direct script execution
# Add parent directory to path for direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative imports first (when run as module), then absolute (when run as script)
try:
    from .models import UIElement, UISnapshot, ElementSelector
except (ImportError, ValueError):
    from ui_twin.models import UIElement, UISnapshot, ElementSelector


class UITwinService:
    """
    Maintains a real-time digital twin of the UI state.
    
    Consumes:
    - Accessibility events from AccessibilityBridge (ws://localhost:8766)
    - Screen frames from CaptureService (ws://localhost:8765)
    
    Provides:
    - Element lookup by selector
    - Temporal buffer of UI history
    - State serialization for persistence
    """
    
    def __init__(self, snapshot_buffer_size: int = 200):
        self.elements: Dict[str, UIElement] = {}
        self.snapshots: deque = deque(maxlen=snapshot_buffer_size)
        self.lock = threading.RLock()
        self._running = False
        
    async def start(self):
        """Start the UI Twin service"""
        logger.info("🎭 Starting UI Twin service...")
        self._running = True
        
        # Start WebSocket consumers
        tasks = [
            asyncio.create_task(self._consume_accessibility_events()),
            asyncio.create_task(self._consume_capture_frames()),
            asyncio.create_task(self._periodic_cleanup()),
        ]
        
        logger.info("✅ UI Twin service started")
        await asyncio.gather(*tasks)
    
    async def _consume_accessibility_events(self):
        """Consume accessibility events from AccessibilityBridge"""
        uri = "ws://localhost:8766/accessibility"
        
        while self._running:
            try:
                async with websockets.connect(uri) as ws:
                    logger.info(f"📡 Connected to AccessibilityBridge at {uri}")
                    
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            
                            if data.get("type") == "accessibility_event":
                                self.apply_accessibility_event(data)
                            elif data.get("type") == "heartbeat":
                                logger.debug(f"💓 Accessibility heartbeat: {data.get('events_captured')} events")
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse accessibility message: {e}")
                            
            except Exception as e:
                logger.warning(f"AccessibilityBridge connection error: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds
    
    async def _consume_capture_frames(self):
        """Consume screen frames from CaptureService (for vision processing)"""
        uri = "ws://localhost:8765/capture"
        frame_count = 0
        
        while self._running:
            try:
                async with websockets.connect(uri) as ws:
                    logger.info(f"📡 Connected to CaptureService at {uri}")
                    
                    async for message in ws:
                        if isinstance(message, bytes):
                            # JPEG frame received
                            frame_count += 1
                            if frame_count % 30 == 0:  # Log every second at 30 FPS
                                logger.debug(f"📸 Received {frame_count} frames")
                            
                            # TODO: Send to vision service for analysis
                            # await self._send_to_vision_service(message)
                            
                        else:
                            # JSON message (heartbeat)
                            try:
                                data = json.loads(message)
                                if data.get("type") == "heartbeat":
                                    logger.debug(f"💓 Capture heartbeat: {data.get('frames_captured')} frames")
                            except json.JSONDecodeError:
                                pass
                                
            except Exception as e:
                logger.warning(f"CaptureService connection error: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds
    
    def apply_accessibility_event(self, event: Dict):
        """Apply an accessibility event to update the UI twin"""
        with self.lock:
            element_id = event.get("element_id")
            if not element_id:
                return
            
            # Update or create element
            if element_id in self.elements:
                elem = self.elements[element_id]
                elem.text = event.get("text", elem.text)
                elem.title = event.get("title", elem.title)
                elem.bbox = tuple(event.get("bbox", elem.bbox))
                elem.window = event.get("window_title", elem.window)
                elem.app_name = event.get("app_name", elem.app_name)
                elem.last_seen = time.time()
                elem.meta["notification_type"] = event.get("notification_type", "")
            else:
                # Create new element
                elem = UIElement(
                    id=element_id,
                    role=event.get("role", "unknown"),
                    text=event.get("text", ""),
                    title=event.get("title", ""),
                    bbox=tuple(event.get("bbox", [0, 0, 0, 0])),
                    window=event.get("window_title", ""),
                    app_name=event.get("app_name", ""),
                    meta={
                        "notification_type": event.get("notification_type", ""),
                        "bundle_id": event.get("bundle_id", ""),
                    }
                )
                self.elements[element_id] = elem
            
            # Add to snapshot history
            snapshot = UISnapshot(
                timestamp=time.time(),
                delta=event,
                snapshot_type="event"
            )
            self.snapshots.append(snapshot)
            
            logger.debug(f"📝 Updated element {element_id}: {elem.role} in {elem.app_name}")
    
    def get_element_by_selector(self, selector: ElementSelector) -> Optional[UIElement]:
        """Find an element by selector"""
        with self.lock:
            for elem in self.elements.values():
                # Match role
                if selector.role and elem.role != selector.role:
                    continue
                
                # Match text (case-insensitive substring)
                if selector.text and selector.text.lower() not in elem.text.lower():
                    continue
                
                # Match title (case-insensitive substring)
                if selector.title and selector.title.lower() not in elem.title.lower():
                    continue
                
                # Match window
                if selector.window and selector.window.lower() not in elem.window.lower():
                    continue
                
                # Match app name
                if selector.app_name and selector.app_name.lower() not in elem.app_name.lower():
                    continue
                
                return elem
            
            return None
    
    def get_elements_by_selector(self, selector: ElementSelector) -> List[UIElement]:
        """Find all elements matching selector"""
        with self.lock:
            results = []
            for elem in self.elements.values():
                # Apply same filtering logic as get_element_by_selector
                if selector.role and elem.role != selector.role:
                    continue
                if selector.text and selector.text.lower() not in elem.text.lower():
                    continue
                if selector.title and selector.title.lower() not in elem.title.lower():
                    continue
                if selector.window and selector.window.lower() not in elem.window.lower():
                    continue
                if selector.app_name and selector.app_name.lower() not in elem.app_name.lower():
                    continue
                
                results.append(elem)
            
            return results
    
    def serialize(self) -> str:
        """Serialize current UI state to JSON"""
        with self.lock:
            data = {
                "elements": {k: v.dict() for k, v in self.elements.items()},
                "snapshot_count": len(self.snapshots),
                "timestamp": time.time()
            }
            return json.dumps(data, indent=2)
    
    async def executeAction(self, selector: ElementSelector, action: str, action_executor_url: str = "http://localhost:8080") -> Dict:
        """
        Execute an action on an element selected by selector.
        
        Args:
            selector: ElementSelector to find the target element
            action: Action type ("click", "type", "press_key")
            action_executor_url: URL of Action Executor service
        
        Returns:
            Dict with action result
        """
        import httpx
        
        # Find element by selector
        element = self.get_element_by_selector(selector)
        if not element:
            return {
                "success": False,
                "error": f"Element not found for selector: {selector.dict()}"
            }
        
        logger.info(f"🎯 Executing {action} on element: {element.role} - {element.text}")
        
        # Translate element to coordinates (use center of bbox)
        x1, y1, x2, y2 = element.bbox
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # Prepare action request
        action_data = {
            "action_id": f"ui_twin_{int(time.time() * 1000)}",
            "action_type": action,
            "x": center_x,
            "y": center_y,
            "element_selector": selector.dict(),
            "verify_after": True
        }
        
        # Add action-specific parameters
        if action == "type" and hasattr(selector, 'text') and selector.text:
            action_data["text"] = selector.text
        
        # Send to Action Executor
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{action_executor_url}/action/execute",
                    json=action_data
                )
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"✅ Action executed: {result.get('status', 'unknown')}")
                return result
                
        except httpx.HTTPError as e:
            error_msg = f"Action Executor request failed: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
        except Exception as e:
            error_msg = f"Action execution error: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
    
    async def _periodic_cleanup(self):
        """Remove stale elements that haven't been seen recently"""
        while self._running:
            await asyncio.sleep(60)  # Run every minute
            
            with self.lock:
                now = time.time()
                stale_threshold = 300  # 5 minutes
                
                stale_ids = [
                    elem_id for elem_id, elem in self.elements.items()
                    if now - elem.last_seen > stale_threshold
                ]
                
                for elem_id in stale_ids:
                    del self.elements[elem_id]
                
                if stale_ids:
                    logger.info(f"🧹 Cleaned up {len(stale_ids)} stale elements")
    
    def stop(self):
        """Stop the UI Twin service"""
        logger.info("⏹️  Stopping UI Twin service...")
        self._running = False


# Main entry point
if __name__ == "__main__":
    service = UITwinService()
    
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        service.stop()
        logger.info("👋 UI Twin service stopped")

