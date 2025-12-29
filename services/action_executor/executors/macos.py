"""
macOS action executor using AccessibilityBridge WebSocket (preferred) or PyAutoGUI fallback
"""

import asyncio
import subprocess
import json
import sys
import os
from typing import Optional
from loguru import logger

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    logger.warning("websockets not installed - will use PyAutoGUI fallback")
    HAS_WEBSOCKETS = False

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    logger.warning("pyautogui not installed - some features may not work")
    pyautogui = None
    HAS_PYAUTOGUI = False

from ..models import Action, ActionType


class MacOSExecutor:
    """Execute actions on macOS using AccessibilityBridge WebSocket (preferred) or PyAutoGUI fallback"""
    
    def __init__(self):
        self.accessibility_ws_url = os.getenv("ACCESSIBILITY_WS_URL", "ws://localhost:8766/accessibility")
        self.use_accessibility_bridge = HAS_WEBSOCKETS
        
        if pyautogui:
            pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    
    async def execute(self, action: Action, element):
        """Execute action on macOS"""
        
        if action.action_type == ActionType.CLICK:
            await self._click(action, element)
        elif action.action_type == ActionType.TYPE:
            await self._type(action)
        elif action.action_type == ActionType.PRESS_KEY:
            await self._press_key(action)
        elif action.action_type == ActionType.SCROLL:
            await self._scroll(action)
        else:
            raise ValueError(f"Unsupported action type: {action.action_type}")
    
    async def _click(self, action: Action, element):
        """Execute click action using AccessibilityBridge or PyAutoGUI"""
        
        # Get coordinates
        if action.x is not None and action.y is not None:
            x, y = action.x, action.y
        elif element:
            # Click center of element
            bbox = element.bbox
            x = (bbox[0] + bbox[2]) // 2
            y = (bbox[1] + bbox[3]) // 2
        else:
            raise ValueError("No coordinates or element provided for click")
        
        logger.info(f"🖱️  Clicking at ({x}, {y})")
        
        # Try AccessibilityBridge first
        if self.use_accessibility_bridge:
            try:
                success = await self._click_via_accessibility(x, y)
                if success:
                    return
            except Exception as e:
                logger.warning(f"AccessibilityBridge click failed: {e}, falling back to PyAutoGUI")
        
        # Fallback to PyAutoGUI
        if not pyautogui:
            raise RuntimeError("Neither AccessibilityBridge nor pyautogui available")
        
        await asyncio.to_thread(pyautogui.click, x, y)
    
    async def _click_via_accessibility(self, x: int, y: int) -> bool:
        """Click via AccessibilityBridge WebSocket"""
        try:
            async with websockets.connect(self.accessibility_ws_url) as ws:
                command = {
                    "command": "click",
                    "x": x,
                    "y": y
                }
                await ws.send(json.dumps(command))
                
                # Wait for response
                response_str = await asyncio.wait_for(ws.recv(), timeout=2.0)
                response = json.loads(response_str)
                
                if response.get("type") == "command_response" and response.get("success"):
                    logger.debug(f"✅ Click successful via AccessibilityBridge")
                    return True
                else:
                    logger.warning(f"❌ Click failed: {response.get('error', 'Unknown error')}")
                    return False
        except Exception as e:
            logger.error(f"AccessibilityBridge connection error: {e}")
            raise
    
    async def _type(self, action: Action):
        """Execute type action using AccessibilityBridge or PyAutoGUI"""
        
        text = action.text
        logger.info(f"⌨️  Typing: {text[:50]}...")
        
        # Try AccessibilityBridge first
        if self.use_accessibility_bridge:
            try:
                success = await self._type_via_accessibility(text)
                if success:
                    return
            except Exception as e:
                logger.warning(f"AccessibilityBridge type failed: {e}, falling back to PyAutoGUI")
        
        # Fallback to PyAutoGUI
        if not pyautogui:
            raise RuntimeError("Neither AccessibilityBridge nor pyautogui available")
        
        await asyncio.to_thread(pyautogui.write, text, interval=0.05)
    
    async def _type_via_accessibility(self, text: str) -> bool:
        """Type text via AccessibilityBridge WebSocket"""
        try:
            async with websockets.connect(self.accessibility_ws_url) as ws:
                command = {
                    "command": "type",
                    "text": text
                }
                await ws.send(json.dumps(command))
                
                # Wait for response
                response_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                response = json.loads(response_str)
                
                if response.get("type") == "command_response" and response.get("success"):
                    logger.debug(f"✅ Type successful via AccessibilityBridge")
                    return True
                else:
                    logger.warning(f"❌ Type failed: {response.get('error', 'Unknown error')}")
                    return False
        except Exception as e:
            logger.error(f"AccessibilityBridge connection error: {e}")
            raise
    
    async def _press_key(self, action: Action):
        """Execute key press action using AccessibilityBridge or PyAutoGUI"""
        
        key = action.key
        logger.info(f"⌨️  Pressing key: {key}")
        
        # Try AccessibilityBridge first
        if self.use_accessibility_bridge:
            try:
                success = await self._press_key_via_accessibility(key)
                if success:
                    return
            except Exception as e:
                logger.warning(f"AccessibilityBridge press_key failed: {e}, falling back to PyAutoGUI")
        
        # Fallback to PyAutoGUI
        if not pyautogui:
            raise RuntimeError("Neither AccessibilityBridge nor pyautogui available")
        
        await asyncio.to_thread(pyautogui.press, key)
    
    async def _press_key_via_accessibility(self, key: str) -> bool:
        """Press key via AccessibilityBridge WebSocket"""
        try:
            async with websockets.connect(self.accessibility_ws_url) as ws:
                command = {
                    "command": "press_key",
                    "key": key
                }
                await ws.send(json.dumps(command))
                
                # Wait for response
                response_str = await asyncio.wait_for(ws.recv(), timeout=2.0)
                response = json.loads(response_str)
                
                if response.get("type") == "command_response" and response.get("success"):
                    logger.debug(f"✅ Press key successful via AccessibilityBridge")
                    return True
                else:
                    logger.warning(f"❌ Press key failed: {response.get('error', 'Unknown error')}")
                    return False
        except Exception as e:
            logger.error(f"AccessibilityBridge connection error: {e}")
            raise
    
    async def _scroll(self, action: Action):
        """Execute scroll action"""
        
        if not pyautogui:
            raise RuntimeError("pyautogui not available")
        
        amount = action.scroll_amount or 100
        logger.info(f"🖱️  Scrolling: {amount}")
        
        await asyncio.to_thread(pyautogui.scroll, amount)

