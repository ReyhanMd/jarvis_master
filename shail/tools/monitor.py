"""
Real-Time System Monitoring Tools - Get current system state.

These tools allow Shail to understand what's happening on the computer in real-time.
"""

import subprocess
import time
from typing import List, Dict
from langchain_core.tools import tool

try:
    from AppKit import NSWorkspace
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False

try:
    import pyautogui
    INPUT_LIBS_AVAILABLE = True
except ImportError:
    INPUT_LIBS_AVAILABLE = False


@tool
def get_active_window() -> str:
    """
    Get the currently active/focused window and application.
    
    Returns:
        String with active app name and window title
    """
    try:
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            try
                set windowTitle to name of first window of frontApp
                return appName & " - " & windowTitle
            on error
                return appName & " (no window title)"
            end try
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Error: {result.stderr}"
    except Exception as e:
        return f"Error getting active window: {str(e)}"


@tool
def get_running_apps() -> str:
    """
    Get list of all currently running applications.
    
    Returns:
        String listing all running apps
    """
    try:
        if APPKIT_AVAILABLE:
            workspace = NSWorkspace.sharedWorkspace()
            apps = workspace.runningApplications()
            app_names = [app.localizedName() for app in apps if app.localizedName()]
            return f"Running applications ({len(app_names)}):\n" + "\n".join(f"  - {name}" for name in sorted(app_names)[:30])
        else:
            script = '''
            tell application "System Events"
                set appList to name of every application process
                return appList
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                apps = result.stdout.strip().split(", ")
                return f"Running applications ({len(apps)}):\n" + "\n".join(f"  - {app}" for app in apps[:30])
            else:
                return f"Error: {result.stderr}"
    except Exception as e:
        return f"Error getting running apps: {str(e)}"


@tool
def get_screen_info() -> str:
    """
    Get current screen information: size, mouse position, active window.
    
    Returns:
        String with comprehensive screen state
    """
    try:
        info_parts = []
        
        # Screen size
        if INPUT_LIBS_AVAILABLE:
            width, height = pyautogui.size()
            info_parts.append(f"Screen: {width}x{height} pixels")
            
            # Mouse position
            x, y = pyautogui.position()
            info_parts.append(f"Mouse: ({x}, {y})")
        
        # Active window
        active = get_active_window()
        info_parts.append(f"Active: {active}")
        
        return "\n".join(info_parts)
    except Exception as e:
        return f"Error getting screen info: {str(e)}"


@tool
def wait_for_window(app_name: str, timeout: int = 5) -> str:
    """
    Wait for a specific application window to become active.
    
    Args:
        app_name: Name of application to wait for
        timeout: Maximum seconds to wait (default: 5)
        
    Returns:
        Success or timeout message
    """
    try:
        start_time = time.time()
        while time.time() - start_time < timeout:
            active = get_active_window()
            if app_name.lower() in active.lower():
                return f"Window '{app_name}' is now active"
            time.sleep(0.2)
        return f"Timeout: '{app_name}' did not become active within {timeout}s"
    except Exception as e:
        return f"Error waiting for window: {str(e)}"

