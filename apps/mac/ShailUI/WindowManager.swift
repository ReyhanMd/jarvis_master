import SwiftUI
import AppKit

/// Manages a floating, non-activating NSPanel window for SHAIL UI
class WindowManager: ObservableObject {
    private var panel: NSPanel?
    private var hostingView: NSHostingView<ContentView>?
    @Published var isVisible: Bool = false
    
    /// Creates and configures the floating panel
    func createPanel(coordinator: ViewCoordinator) {
        // Create NSPanel (not NSWindow) for floating behavior
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 400),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        
        // Configure panel properties
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isFloatingPanel = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isOpaque = false
        
        // Create hosting view with SwiftUI content
        let hostingView = NSHostingView(rootView: ContentView().environmentObject(coordinator))
        hostingView.translatesAutoresizingMaskIntoConstraints = false
        
        // Add visual effect view for glassy appearance
        let visualEffectView = NSVisualEffectView()
        visualEffectView.material = .hudWindow
        visualEffectView.blendingMode = .behindWindow
        visualEffectView.state = .active
        visualEffectView.translatesAutoresizingMaskIntoConstraints = false
        
        panel.contentView = visualEffectView
        
        // Add hosting view to visual effect view
        visualEffectView.addSubview(hostingView)
        
        NSLayoutConstraint.activate([
            hostingView.leadingAnchor.constraint(equalTo: visualEffectView.leadingAnchor),
            hostingView.trailingAnchor.constraint(equalTo: visualEffectView.trailingAnchor),
            hostingView.topAnchor.constraint(equalTo: visualEffectView.topAnchor),
            hostingView.bottomAnchor.constraint(equalTo: visualEffectView.bottomAnchor)
        ])
        
        // Position in bottom-right corner
        if let screen = NSScreen.main {
            let screenRect = screen.visibleFrame
            let panelWidth: CGFloat = 500
            let panelHeight: CGFloat = 400
            let x = screenRect.maxX - panelWidth - 20
            let y = screenRect.minY + 20
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }
        
        self.panel = panel
        self.hostingView = hostingView
    }
    
    /// Shows the panel
    func show() {
        guard let panel = panel else { return }
        panel.orderFront(nil)
        isVisible = true
    }
    
    /// Hides the panel
    func hide() {
        guard let panel = panel else { return }
        panel.orderOut(nil)
        isVisible = false
    }
    
    /// Toggles panel visibility
    func toggle() {
        if isVisible {
            hide()
        } else {
            show()
        }
    }
    
    /// Centers the panel on screen
    func center() {
        guard let panel = panel, let screen = NSScreen.main else { return }
        let screenRect = screen.visibleFrame
        let panelRect = panel.frame
        let x = screenRect.midX - panelRect.width / 2
        let y = screenRect.midY - panelRect.height / 2
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }
}

