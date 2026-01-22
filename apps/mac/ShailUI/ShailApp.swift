import SwiftUI
import AppKit

@main
struct ShailApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    var body: some Scene {
        Settings {
            EmptyView()
        }
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(replacing: .saveItem) {}
        }
    }
}

// App delegate to handle AppKit lifecycle
class AppDelegate: NSObject, NSApplicationDelegate {
    var windowManager: WindowManager?
    let coordinator = ViewCoordinator()
    var hotkeyListener: GlobalInputListener?
    
    override init() {
        super.init()
    }
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Create window manager
        windowManager = WindowManager()
        windowManager?.createPanel(coordinator: coordinator, startInLauncher: true)
        coordinator.collapseToLauncher = { [weak self] in
            self?.windowManager?.collapseToLauncher()
        }
        
        // Create and start hotkey listener
        hotkeyListener = GlobalInputListener()
        hotkeyListener?.startMonitoring { [weak self] in
            self?.windowManager?.toggle()
        }
        
        // Initially hide the panel (user will show it with Option+S)
        windowManager?.hide()
        
        // Hide dock icon (optional - makes it more like a background service)
        NSApp.setActivationPolicy(.accessory)
    }
    
    func applicationWillTerminate(_ notification: Notification) {
        hotkeyListener?.stopMonitoring()
    }
    
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        // Show panel when app icon is clicked
        windowManager?.toggle()
        return true
    }
}
