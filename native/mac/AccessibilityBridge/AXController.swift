import Foundation
import ApplicationServices
import CoreGraphics
import Cocoa

/// Controller for executing accessibility actions (click, type, etc.)
class AXController {
    
    /// Click at specified coordinates using CGEvent
    static func click(x: Int, y: Int) -> Bool {
        let point = CGPoint(x: CGFloat(x), y: CGFloat(y))
        
        // Create mouse down event
        guard let mouseDown = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left) else {
            return false
        }
        
        // Create mouse up event
        guard let mouseUp = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
            return false
        }
        
        // Post events
        mouseDown.post(tap: .cghidEventTap)
        mouseUp.post(tap: .cghidEventTap)
        
        return true
    }
    
    /// Type text using CGEvent
    static func typeText(_ text: String) -> Bool {
        // Create keyboard events for each character
        for char in text {
            let keyCode = getKeyCode(for: char)
            let keyDown = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: true)
            let keyUp = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: false)
            
            keyDown?.post(tap: .cghidEventTap)
            keyUp?.post(tap: .cghidEventTap)
            
            // Small delay between keystrokes for reliability
            usleep(10000) // 10ms
        }
        
        return true
    }
    
    /// Press a specific key
    static func pressKey(_ key: String) -> Bool {
        let keyCode = getKeyCode(for: key)
        guard keyCode != 0 else {
            return false
        }
        
        let keyDown = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: true)
        let keyUp = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: false)
        
        keyDown?.post(tap: .cghidEventTap)
        keyUp?.post(tap: .cghidEventTap)
        
        return true
    }
    
    /// Get information about the active window
    static func getActiveWindowInfo() -> [String: Any] {
        var info: [String: Any] = [:]
        
        // Get frontmost application
        guard let frontApp = NSWorkspace.shared.frontmostApplication else {
            return info
        }
        
        info["app_name"] = frontApp.localizedName ?? "Unknown"
        info["bundle_id"] = frontApp.bundleIdentifier ?? ""
        info["pid"] = frontApp.processIdentifier
        
        // Get active window
        let pid = frontApp.processIdentifier
        let appElement = AXUIElementCreateApplication(pid)
        
        var windowList: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(
            appElement,
            kAXWindowsAttribute as CFString,
            &windowList
        )
        
        if result == .success, let windows = windowList as? [AXUIElement], !windows.isEmpty {
            let mainWindow = windows[0] // Usually the first window is the main one
            
            // Get window title
            if let title = getAttributeValue(mainWindow, kAXTitleAttribute as CFString) as? String {
                info["window_title"] = title
            }
            
            // Get window position and size
            if let positionRef = getAttributeValue(mainWindow, kAXPositionAttribute as CFString) {
                let position = unsafeBitCast(positionRef, to: AXValue.self)
                var point = CGPoint.zero
                if AXValueGetValue(position, .cgPoint, &point) {
                    info["window_x"] = Int(point.x)
                    info["window_y"] = Int(point.y)
                }
            }
            
            if let sizeRef = getAttributeValue(mainWindow, kAXSizeAttribute as CFString) {
                let size = unsafeBitCast(sizeRef, to: AXValue.self)
                var cgSize = CGSize.zero
                if AXValueGetValue(size, .cgSize, &cgSize) {
                    info["window_width"] = Int(cgSize.width)
                    info["window_height"] = Int(cgSize.height)
                }
            }
        }
        
        return info
    }
    
    /// Get AXUIElement at specified coordinates
    static func getElementAt(x: Int, y: Int) -> [String: Any]? {
        let point = CGPoint(x: CGFloat(x), y: CGFloat(y))
        
        // Get system-wide element
        let systemWide = AXUIElementCreateSystemWide()
        
        // Get element at point
        var elementRef: CFTypeRef?
        let result = AXUIElementCopyElementAtPosition(systemWide, Float(point.x), Float(point.y), &elementRef)
        
        guard result == .success, let element = elementRef else {
            return nil
        }
        
        let elementUI = unsafeBitCast(element, to: AXUIElement.self)
        
        // Get element info
        var pid: pid_t = 0
        AXUIElementGetPid(elementUI, &pid)
        
        var info: [String: Any] = [
            "x": x,
            "y": y,
            "pid": pid
        ]
        
        // Get app name
        if let app = NSRunningApplication(processIdentifier: pid) {
            info["app_name"] = app.localizedName ?? "Unknown"
            info["bundle_id"] = app.bundleIdentifier ?? ""
        }
        
        // Get role
        if let role = getAttributeValue(elementUI, kAXRoleAttribute as CFString) as? String {
            info["role"] = role
        }
        
        // Get title
        if let title = getAttributeValue(elementUI, kAXTitleAttribute as CFString) as? String {
            info["title"] = title
        }
        
        // Get value/text
        if let value = getAttributeValue(elementUI, kAXValueAttribute as CFString) {
            if let stringValue = value as? String {
                info["text"] = stringValue
            }
        }
        
        // Get position and size
        if let positionRef = getAttributeValue(elementUI, kAXPositionAttribute as CFString) {
            let position = unsafeBitCast(positionRef, to: AXValue.self)
            var pos = CGPoint.zero
            if AXValueGetValue(position, .cgPoint, &pos) {
                info["element_x"] = Int(pos.x)
                info["element_y"] = Int(pos.y)
            }
        }
        
        if let sizeRef = getAttributeValue(elementUI, kAXSizeAttribute as CFString) {
            let size = unsafeBitCast(sizeRef, to: AXValue.self)
            var cgSize = CGSize.zero
            if AXValueGetValue(size, .cgSize, &cgSize) {
                info["element_width"] = Int(cgSize.width)
                info["element_height"] = Int(cgSize.height)
            }
        }
        
        return info
    }
    
    // MARK: - Helper Methods
    
    private static func getAttributeValue(_ element: AXUIElement, _ attribute: CFString) -> CFTypeRef? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        return result == .success ? value : nil
    }
    
    private static func getKeyCode(for character: Character) -> CGKeyCode {
        // Map common characters to key codes
        // This is a simplified mapping - for production, use a more complete mapping
        let charString = String(character).lowercased()
        
        switch charString {
        case "a": return 0
        case "b": return 11
        case "c": return 8
        case "d": return 2
        case "e": return 14
        case "f": return 3
        case "g": return 5
        case "h": return 4
        case "i": return 34
        case "j": return 38
        case "k": return 40
        case "l": return 37
        case "m": return 46
        case "n": return 45
        case "o": return 31
        case "p": return 35
        case "q": return 12
        case "r": return 15
        case "s": return 1
        case "t": return 17
        case "u": return 32
        case "v": return 9
        case "w": return 13
        case "x": return 7
        case "y": return 16
        case "z": return 6
        case "0": return 29
        case "1": return 18
        case "2": return 19
        case "3": return 20
        case "4": return 21
        case "5": return 23
        case "6": return 22
        case "7": return 26
        case "8": return 28
        case "9": return 25
        case " ": return 49 // Space
        case "\n", "\r": return 36 // Return/Enter
        case "\t": return 48 // Tab
        default:
            // For special characters, try to use Unicode
            // In production, use a proper key code mapping library
            return 0
        }
    }
    
    private static func getKeyCode(for key: String) -> CGKeyCode {
        // Map common key names to key codes
        switch key.lowercased() {
        case "enter", "return": return 36
        case "tab": return 48
        case "space": return 49
        case "delete", "backspace": return 51
        case "escape", "esc": return 53
        case "command", "cmd": return 55
        case "shift": return 56
        case "option", "alt": return 58
        case "control", "ctrl": return 59
        case "up": return 126
        case "down": return 125
        case "left": return 123
        case "right": return 124
        default:
            // Try to get key code for single character
            if key.count == 1 {
                return getKeyCode(for: Character(key))
            }
            return 0
        }
    }
}

