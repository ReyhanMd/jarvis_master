import SwiftUI
import AppKit

/// Global hotkey listener for Option+S to toggle SHAIL panel
/// Uses NSEvent global monitor (requires Input Monitoring permission)
class GlobalInputListener: ObservableObject {
    private var eventMonitor: Any?
    private var toggleCallback: (() -> Void)?
    
    /// Starts monitoring for Option+S hotkey
    /// Note: Requires Input Monitoring permission in System Settings
    func startMonitoring(toggleCallback: @escaping () -> Void) {
        self.toggleCallback = toggleCallback
        
        // Use NSEvent global monitor (simpler and more reliable than Carbon API)
        eventMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown]) { [weak self] event in
            guard let self = self else { return }
            
            // Check for Option+S (Option modifier + S key)
            // S key code is 1, Option modifier is .option
            if event.modifierFlags.contains(.option) && event.keyCode == 1 {
                DispatchQueue.main.async {
                    self.toggleCallback?()
                }
            }
        }
        
        // Also monitor local events (for when app is active)
        NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) { event in
            if event.modifierFlags.contains(.option) && event.keyCode == 1 {
                DispatchQueue.main.async {
                    toggleCallback()
                }
                return nil // Consume the event
            }
            return event
        }
    }
    
    /// Stops monitoring
    func stopMonitoring() {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
            eventMonitor = nil
        }
        toggleCallback = nil
    }
    
    deinit {
        stopMonitoring()
    }
}

