import Foundation
import ApplicationServices

class AXPermissionManager {
    static let shared = AXPermissionManager()
    
    private init() {}
    
    func checkAccessibilityPermission() -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: false]
        return AXIsProcessTrustedWithOptions(options as CFDictionary)
    }
    
    func requestAccessibilityPermission() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
        
        print("⚠️  Please enable Accessibility permissions:")
        print("   1. Open System Preferences")
        print("   2. Go to Privacy & Security > Accessibility")
        print("   3. Enable access for AccessibilityBridge")
        print("   4. Restart this application")
    }
}

