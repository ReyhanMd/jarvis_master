"""
Windows action executor using PyAutoGUI and UI Automation
"""

import asyncio
from typing import Optional
from loguru import logger

try:
    import pyautogui
except ImportError:
    logger.warning("pyautogui not installed - some features may not work")
    pyautogui = None

from ..models import Action, ActionType


class WindowsExecutor:
    """Execute actions on Windows"""
    
    def __init__(self):
        if pyautogui:
            pyautogui.FAILSAFE = True
    
    async def execute(self, action: Action, element):
        """Execute action on Windows"""
        
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
        """Execute click action"""
        
        if not pyautogui:
            raise RuntimeError("pyautogui not available")
        
        # Get coordinates
        if action.x is not None and action.y is not None:
            x, y = action.x, action.y
        elif element:
            bbox = element.bbox
            x = (bbox[0] + bbox[2]) // 2
            y = (bbox[1] + bbox[3]) // 2
        else:
            raise ValueError("No coordinates or element provided for click")
        
        logger.info(f"🖱️  Clicking at ({x}, {y})")
        await asyncio.to_thread(pyautogui.click, x, y)
    
    async def _type(self, action: Action):
        """Execute type action"""
        
        if not pyautogui:
            raise RuntimeError("pyautogui not available")
        
        text = action.text
        logger.info(f"⌨️  Typing: {text[:50]}...")
        await asyncio.to_thread(pyautogui.write, text, interval=0.05)
    
    async def _press_key(self, action: Action):
        """Execute key press action"""
        
        if not pyautogui:
            raise RuntimeError("pyautogui not available")
        
        key = action.key
        logger.info(f"⌨️  Pressing key: {key}")
        await asyncio.to_thread(pyautogui.press, key)
    
    async def _scroll(self, action: Action):
        """Execute scroll action"""
        
        if not pyautogui:
            raise RuntimeError("pyautogui not available")
        
        amount = action.scroll_amount or 100
        logger.info(f"🖱️  Scrolling: {amount}")
        await asyncio.to_thread(pyautogui.scroll, amount)

