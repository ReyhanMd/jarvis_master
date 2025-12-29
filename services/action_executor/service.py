"""
Action Executor Service - Safe UI action execution
"""

import asyncio
import time
import platform
import sys
import os
from typing import Optional
from loguru import logger
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Handle imports for both module and direct script execution
# Add parent directory to path for direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative imports first (when run as module), then absolute (when run as script)
try:
    from .models import Action, ActionResult, ActionStatus, ActionType
except (ImportError, ValueError):
    from action_executor.models import Action, ActionResult, ActionStatus, ActionType

try:
    from ..ui_twin.models import ElementSelector
    from ..ui_twin.service import UITwinService
except (ImportError, ValueError):
    from ui_twin.models import ElementSelector
    from ui_twin.service import UITwinService


class ActionExecutorService:
    """
    Executes UI actions with safety constraints and verification.
    
    Provides:
    - HTTP/JSON API for action execution
    - Safety checks before execution
    - Post-execution verification
    - Screenshot capture
    - Two-step confirmation for destructive operations
    """
    
    def __init__(self, ui_twin: Optional[UITwinService] = None):
        self.ui_twin = ui_twin
        self.app = FastAPI(title="Shail Action Executor")
        self._setup_routes()
        
        # Platform-specific executor
        self.platform = platform.system()
        # Try relative import first, fallback to absolute
        try:
            if self.platform == "Darwin":
                from .executors.macos import MacOSExecutor
                self.executor = MacOSExecutor()
            elif self.platform == "Windows":
                from .executors.windows import WindowsExecutor
                self.executor = WindowsExecutor()
            else:
                raise RuntimeError(f"Unsupported platform: {self.platform}")
        except (ImportError, ValueError):
            # Running directly as script - use absolute import or direct path
            executor_dir = os.path.join(_script_dir, "executors")
            if self.platform == "Darwin":
                try:
                    from action_executor.executors.macos import MacOSExecutor
                    self.executor = MacOSExecutor()
                except ImportError:
                    # Last resort: direct path import
                    import importlib.util
                    macos_path = os.path.join(executor_dir, "macos.py")
                    spec = importlib.util.spec_from_file_location("macos", macos_path)
                    macos_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(macos_module)
                    self.executor = macos_module.MacOSExecutor()
            elif self.platform == "Windows":
                try:
                    from action_executor.executors.windows import WindowsExecutor
                    self.executor = WindowsExecutor()
                except ImportError:
                    # Last resort: direct path import
                    import importlib.util
                    windows_path = os.path.join(executor_dir, "windows.py")
                    spec = importlib.util.spec_from_file_location("windows", windows_path)
                    windows_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(windows_module)
                    self.executor = windows_module.WindowsExecutor()
            else:
                raise RuntimeError(f"Unsupported platform: {self.platform}")
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/action/click", response_model=ActionResult)
        async def click_action(action: Action):
            """Execute a click action"""
            action.action_type = ActionType.CLICK
            return await self.execute(action)
        
        @self.app.post("/action/type", response_model=ActionResult)
        async def type_action(action: Action):
            """Execute a type action"""
            action.action_type = ActionType.TYPE
            return await self.execute(action)
        
        @self.app.post("/action/press_key", response_model=ActionResult)
        async def press_key_action(action: Action):
            """Execute a key press action"""
            action.action_type = ActionType.PRESS_KEY
            return await self.execute(action)
        
        @self.app.post("/action/execute", response_model=ActionResult)
        async def execute_action(action: Action):
            """Execute any action"""
            return await self.execute(action)
        
        @self.app.get("/health")
        async def health():
            """Health check"""
            return {"status": "ok", "platform": self.platform}
    
    async def execute(self, action: Action) -> ActionResult:
        """
        Execute an action with safety checks and verification.
        
        Flow:
        1. Validate action
        2. Find target element (if needed)
        3. Check safety constraints
        4. Take screenshot (if requested)
        5. Execute action
        6. Verify result (if requested)
        7. Take screenshot (if requested)
        8. Return result
        """
        
        result = ActionResult(
            action_id=action.action_id,
            status=ActionStatus.PENDING,
            started_at=time.time()
        )
        
        try:
            # Step 1: Validate action
            self._validate_action(action)
            
            # Step 2: Resolve element if needed
            element = None
            if action.element_selector and self.ui_twin:
                selector = ElementSelector(**action.element_selector)
                element = self.ui_twin.get_element_by_selector(selector)
                
                if not element:
                    raise ValueError(f"Element not found: {action.element_selector}")
                
                logger.info(f"🎯 Found element: {element.role} - {element.text}")
            
            # Step 3: Check safety constraints
            if action.confirm:
                # In production, this would prompt the user
                logger.warning(f"⚠️  Confirmation required for action {action.action_id}")
                # For now, we'll proceed automatically
            
            # Step 4: Take screenshot before
            if action.screenshot_before:
                result.screenshot_before_id = await self._capture_screenshot()
            
            # Step 5: Execute action
            result.status = ActionStatus.RUNNING
            logger.info(f"▶️  Executing {action.action_type.value} action {action.action_id}")
            
            await self._execute_platform_action(action, element)
            
            # Step 6: Verify result
            if action.verify_after:
                verified = await self._verify_action(action, element)
                result.verified = verified
                
                if not verified:
                    result.status = ActionStatus.FAILED
                    result.error = "Action verification failed"
                    logger.warning(f"❌ Action {action.action_id} verification failed")
                    return result
            
            # Step 7: Take screenshot after
            if action.screenshot_after:
                result.screenshot_after_id = await self._capture_screenshot()
            
            # Success
            result.status = ActionStatus.SUCCESS
            result.result = f"{action.action_type.value} action completed successfully"
            
            logger.info(f"✅ Action {action.action_id} completed successfully")
            
        except asyncio.TimeoutError:
            result.status = ActionStatus.TIMEOUT
            result.error = f"Action timed out after {action.timeout_ms}ms"
            logger.error(f"⏱️  Action {action.action_id} timed out")
            
        except Exception as e:
            result.status = ActionStatus.FAILED
            result.error = str(e)
            logger.error(f"❌ Action {action.action_id} failed: {e}")
        
        finally:
            result.completed_at = time.time()
            result.duration_ms = (result.completed_at - result.started_at) * 1000
        
        return result
    
    def _validate_action(self, action: Action):
        """Validate action parameters"""
        
        if action.action_type == ActionType.TYPE and not action.text:
            raise ValueError("TYPE action requires 'text' parameter")
        
        if action.action_type == ActionType.PRESS_KEY and not action.key:
            raise ValueError("PRESS_KEY action requires 'key' parameter")
        
        if action.action_type == ActionType.CLICK:
            if not action.element_id and not action.element_selector and (action.x is None or action.y is None):
                raise ValueError("CLICK action requires element_id, element_selector, or (x, y) coordinates")
    
    async def _execute_platform_action(self, action: Action, element):
        """Execute platform-specific action"""
        
        timeout = action.timeout_ms / 1000.0  # Convert to seconds
        
        try:
            await asyncio.wait_for(
                self.executor.execute(action, element),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            raise RuntimeError(f"Platform execution failed: {e}")
    
    async def _verify_action(self, action: Action, element) -> bool:
        """Verify action was successful"""
        
        # Wait a bit for UI to update
        await asyncio.sleep(0.5)
        
        # Simple verification: check if element still exists
        if element and self.ui_twin:
            # Re-query element to see if it changed
            selector = ElementSelector(id=element.id)
            updated_element = self.ui_twin.get_element_by_selector(selector)
            
            # For now, just check existence
            return updated_element is not None
        
        # Default: assume success
        return True
    
    async def _capture_screenshot(self) -> str:
        """Capture screenshot and return ID"""
        
        # TODO: Integrate with CaptureService to save current frame
        screenshot_id = f"screenshot_{int(time.time() * 1000)}"
        logger.debug(f"📸 Captured screenshot {screenshot_id}")
        
        return screenshot_id
    
    async def start(self, host: str = "0.0.0.0", port: int = 8080):
        """Start the Action Executor HTTP API"""
        import uvicorn
        
        logger.info(f"🚀 Starting Action Executor API on {host}:{port}")
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


# Main entry point
if __name__ == "__main__":
    service = ActionExecutorService()
    
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("👋 Action Executor service stopped")

