import SwiftUI
import AppKit

/// Listens for ⌘+Shift+S globally to toggle the SHAIL panel.
/// Requires Input Monitoring permission (System Settings → Privacy & Security).
class GlobalInputListener: ObservableObject {
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var toggleCallback: (() -> Void)?

    func startMonitoring(toggleCallback: @escaping () -> Void) {
        self.toggleCallback = toggleCallback

        // Global monitor fires even when SHAIL is in background
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if self?.isShailHotkey(event) == true {
                DispatchQueue.main.async { self?.toggleCallback?() }
            }
        }

        // Local monitor fires when SHAIL panel is frontmost
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if self?.isShailHotkey(event) == true {
                DispatchQueue.main.async { self?.toggleCallback?() }
                return nil // consume the event
            }
            return event
        }
    }

    func stopMonitoring() {
        if let monitor = globalMonitor { NSEvent.removeMonitor(monitor) }
        if let monitor = localMonitor  { NSEvent.removeMonitor(monitor) }
        globalMonitor = nil
        localMonitor  = nil
        toggleCallback = nil
    }

    deinit { stopMonitoring() }

    // MARK: - Hotkey definition: ⌘ + Shift + S

    private func isShailHotkey(_ event: NSEvent) -> Bool {
        let required: NSEvent.ModifierFlags = [.command, .shift]
        let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        // keyCode 1 = S key
        return modifiers == required && event.keyCode == 1
    }
}
