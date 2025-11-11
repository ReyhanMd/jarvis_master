"""
Desktop Control Tools - Mouse, Keyboard, and Window Management.

These tools allow Shail to control the desktop environment for hands-free interaction.
All potentially dangerous operations require user approval via the permission system.
"""

import time
import subprocess
from typing import List, Tuple, Optional
from langchain_core.tools import tool
from shail.safety.exceptions import PermissionRequired

# macOS-specific imports
try:
    from AppKit import NSWorkspace, NSApplicationActivateIgnoringOtherApps
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False

try:
    import pyautogui
    from pynput.keyboard import Key, Controller as KeyboardController
    from pynput.mouse import Button, Controller as MouseController
    INPUT_LIBS_AVAILABLE = True
except ImportError:
    INPUT_LIBS_AVAILABLE = False


# Safety: Enable PyAutoGUI failsafe (move mouse to corner to abort)
if INPUT_LIBS_AVAILABLE:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1  # Small delay between actions


# Initialize controllers (only if libraries available)
if INPUT_LIBS_AVAILABLE:
    _keyboard = KeyboardController()
    _mouse = MouseController()
else:
    _keyboard = None
    _mouse = None


# Special key mappings
SPECIAL_KEYS = {
    "enter": Key.enter,
    "space": Key.space,
    "tab": Key.tab,
    "shift": Key.shift,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "win": Key.cmd,
    "esc": Key.esc,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "caps_lock": Key.caps_lock,
}


def _check_input_libs():
    """Check if input libraries are available."""
    if not INPUT_LIBS_AVAILABLE:
        raise RuntimeError(
            "Desktop control requires pyautogui and pynput. "
            "Install with: pip install pyautogui pynput"
        )


@tool
def move_mouse(x: int, y: int) -> str:
    """
    Move the mouse cursor to specific coordinates (x, y) on the screen.
    
    Args:
        x: X coordinate (pixels from left edge)
        y: Y coordinate (pixels from top edge)
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="move_mouse",
        args={"x": x, "y": y},
        rationale=f"Moving mouse cursor to coordinates ({x}, {y})"
    )


def _execute_move_mouse_approved(x: int, y: int) -> str:
    """Execute move_mouse after approval."""
    _check_input_libs()
    try:
        pyautogui.moveTo(x, y, duration=0.2)
        return f"Mouse moved to ({x}, {y})"
    except Exception as e:
        return f"Error moving mouse: {str(e)}"


@tool
def click_mouse(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> str:
    """
    Click the mouse at the current position or specified coordinates.
    
    Args:
        button: Mouse button to click ("left", "right", or "middle")
        x: Optional X coordinate (if None, clicks at current position)
        y: Optional Y coordinate (if None, clicks at current position)
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="click_mouse",
        args={"button": button, "x": x, "y": y},
        rationale=f"Clicking {button} mouse button" + (f" at ({x}, {y})" if x and y else " at current position")
    )


def _execute_click_mouse_approved(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> str:
    """Execute click_mouse after approval."""
    _check_input_libs()
    try:
        if button == "left":
            btn = Button.left
        elif button == "right":
            btn = Button.right
        elif button == "middle":
            btn = Button.middle
        else:
            return f"Invalid button: {button}. Use 'left', 'right', or 'middle'"
        
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.1)
            time.sleep(0.1)
        
        _mouse.click(btn, 1)
        return f"Mouse {button} clicked" + (f" at ({x}, {y})" if x and y else "")
    except Exception as e:
        return f"Error clicking mouse: {str(e)}"


@tool
def type_text(text: str) -> str:
    """
    Type text character by character, as if entered from keyboard.
    
    Args:
        text: The text to type
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="type_text",
        args={"text": text},
        rationale=f"Typing text: '{text[:50]}...' (length: {len(text)} chars)"
    )


def _execute_type_text_approved(text: str) -> str:
    """Execute type_text after approval."""
    _check_input_libs()
    try:
        # Type character by character
        for char in text:
            if char == "\n":
                _keyboard.press(Key.enter)
                _keyboard.release(Key.enter)
            elif char == "\t":
                _keyboard.press(Key.tab)
                _keyboard.release(Key.tab)
            elif char.isprintable():
                _keyboard.press(char)
                _keyboard.release(char)
            time.sleep(0.05)  # Small delay between characters
        
        return f"Typed {len(text)} characters"
    except Exception as e:
        return f"Error typing text: {str(e)}"


@tool
def press_key(key: str) -> str:
    """
    Press a single keyboard key.
    
    Args:
        key: Key name (e.g., "enter", "esc", "a", "1", "cmd", "ctrl")
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="press_key",
        args={"key": key},
        rationale=f"Pressing key: {key}"
    )


def _execute_press_key_approved(key: str) -> str:
    """Execute press_key after approval."""
    _check_input_libs()
    try:
        # Resolve special keys
        if key.lower() in SPECIAL_KEYS:
            k = SPECIAL_KEYS[key.lower()]
        else:
            k = key.lower()
        
        _keyboard.press(k)
        _keyboard.release(k)
        return f"Pressed key: {key}"
    except Exception as e:
        return f"Error pressing key: {str(e)}"


@tool
def press_hotkey(keys: List[str]) -> str:
    """
    Press a keyboard shortcut (multiple keys simultaneously).
    
    Args:
        keys: List of key names (e.g., ["cmd", "c"] for Copy)
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="press_hotkey",
        args={"keys": keys},
        rationale=f"Pressing hotkey: {' + '.join(keys)}"
    )


def _execute_press_hotkey_approved(keys: List[str]) -> str:
    """Execute press_hotkey after approval."""
    _check_input_libs()
    try:
        resolved_keys = []
        for k in keys:
            if k.lower() in SPECIAL_KEYS:
                resolved_keys.append(SPECIAL_KEYS[k.lower()])
            else:
                resolved_keys.append(k.lower())
        
        # Press all keys
        for k in resolved_keys:
            _keyboard.press(k)
        
        # Release in reverse order
        for k in reversed(resolved_keys):
            _keyboard.release(k)
        
        return f"Pressed hotkey: {' + '.join(keys)}"
    except Exception as e:
        return f"Error pressing hotkey: {str(e)}"


@tool
def scroll_mouse(direction: str, amount: int = 3) -> str:
    """
    Scroll the mouse wheel up or down.
    
    Args:
        direction: Scroll direction ("up" or "down")
        amount: Number of scroll units (default: 3)
        
    Returns:
        Confirmation message
    """
    # Desktop control requires permission
    raise PermissionRequired(
        tool_name="scroll_mouse",
        args={"direction": direction, "amount": amount},
        rationale=f"Scrolling {direction} {amount} units"
    )


def _execute_scroll_mouse_approved(direction: str, amount: int = 3) -> str:
    """Execute scroll_mouse after approval."""
    _check_input_libs()
    try:
        scroll_value = amount if direction.lower() == "up" else -amount
        pyautogui.scroll(scroll_value)
        return f"Scrolled {direction} {amount} units"
    except Exception as e:
        return f"Error scrolling: {str(e)}"


@tool
def get_mouse_position() -> str:
    """
    Get the current mouse cursor position.
    
    Returns:
        String with current (x, y) coordinates
    """
    _check_input_libs()
    try:
        x, y = pyautogui.position()
        return f"Mouse position: ({x}, {y})"
    except Exception as e:
        return f"Error getting mouse position: {str(e)}"


@tool
def get_screen_size() -> str:
    """
    Get the screen resolution/dimensions.
    
    Returns:
        String with screen width and height
    """
    _check_input_libs()
    try:
        width, height = pyautogui.size()
        return f"Screen size: {width}x{height} pixels"
    except Exception as e:
        return f"Error getting screen size: {str(e)}"


# ==================== Window Management Tools ====================

@tool
def focus_window(app_name: str) -> str:
    """
    Focus/bring to front a window for a specific application.
    
    Args:
        app_name: Name of the application (e.g., "Safari", "Terminal", "VS Code")
        
    Returns:
        Confirmation message
    """
    # Window management requires permission
    raise PermissionRequired(
        tool_name="focus_window",
        args={"app_name": app_name},
        rationale=f"Focusing window for application: {app_name}"
    )


def _execute_focus_window_approved(app_name: str) -> str:
    """Execute focus_window after approval."""
    try:
        if APPKIT_AVAILABLE:
            # Use AppKit for macOS
            workspace = NSWorkspace.sharedWorkspace()
            apps = workspace.runningApplications()
            
            for app in apps:
                if app.localizedName() and app_name.lower() in app.localizedName().lower():
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    return f"Focused window for {app.localizedName()}"
            
            return f"Application '{app_name}' not found or not running"
        else:
            # Fallback to AppleScript
            script = f'''
            tell application "System Events"
                set frontmost of process "{app_name}" to true
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return f"Focused window for {app_name}"
            else:
                return f"Error focusing window: {result.stderr}"
    except Exception as e:
        return f"Error focusing window: {str(e)}"


@tool
def get_window_position(app_name: str) -> str:
    """
    Get the position and size of a window for a specific application.
    
    Args:
        app_name: Name of the application
        
    Returns:
        String with window position and size information
    """
    try:
        if APPKIT_AVAILABLE:
            workspace = NSWorkspace.sharedWorkspace()
            apps = workspace.runningApplications()
            
            for app in apps:
                if app.localizedName() and app_name.lower() in app.localizedName().lower():
                    # Get window info via AppleScript
                    script = f'''
                    tell application "System Events"
                        tell process "{app.localizedName()}"
                            if exists window 1 then
                                set windowPos to position of window 1
                                set windowSize to size of window 1
                                return "Position: " & (item 1 of windowPos) & ", " & (item 2 of windowPos) & " | Size: " & (item 1 of windowSize) & "x" & (item 2 of windowSize)
                            end if
                        end tell
                    end tell
                    '''
                    result = subprocess.run(
                        ["osascript", "-e", script],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
                    else:
                        return f"Window not found or not accessible for {app.localizedName()}"
            
            return f"Application '{app_name}' not found"
        else:
            # Fallback to AppleScript
            script = f'''
            tell application "System Events"
                tell process "{app_name}"
                    if exists window 1 then
                        set windowPos to position of window 1
                        set windowSize to size of window 1
                        return "Position: " & (item 1 of windowPos) & ", " & (item 2 of windowPos) & " | Size: " & (item 1 of windowSize) & "x" & (item 2 of windowSize)
                    end if
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Error getting window position: {result.stderr}"
    except Exception as e:
        return f"Error getting window position: {str(e)}"


@tool
def list_open_windows() -> str:
    """
    List all currently open application windows.
    
    Returns:
        String listing all open windows
    """
    try:
        script = '''
        tell application "System Events"
            set windowList to {}
            repeat with proc in every process
                try
                    set procName to name of proc
                    repeat with win in every window of proc
                        try
                            set winTitle to title of win
                            set windowList to windowList & (procName & ": " & winTitle)
                        end try
                    end repeat
                end try
            end repeat
            return windowList
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            windows = result.stdout.strip().split(", ")
            if windows and windows[0]:
                return f"Open windows:\n" + "\n".join(f"  - {w}" for w in windows[:20])  # Limit to 20
            else:
                return "No windows found or accessible"
        else:
            return f"Error listing windows: {result.stderr}"
    except Exception as e:
        return f"Error listing windows: {str(e)}"
