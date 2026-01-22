import SwiftUI
import AppKit

/// Manages a floating, non-activating NSPanel window for SHAIL UI
class WindowManager: ObservableObject {
    private var panel: NSPanel?
    private var hostingView: NSHostingView<AnyView>?
    private var containerView: NSVisualEffectView?
    private weak var coordinator: ViewCoordinator?
    @Published var isVisible: Bool = false
    @Published private(set) var isLauncherMode: Bool = true
    
    /// Creates and configures the floating panel
    func createPanel(coordinator: ViewCoordinator, startInLauncher: Bool = true) {
        self.coordinator = coordinator
        self.isLauncherMode = startInLauncher
        
        // Create NSPanel (not NSWindow) for floating behavior
        let initialSize = sizeForMode(isLauncher: isLauncherMode)
        let panel = FloatingPanel(
            contentRect: NSRect(x: 0, y: 0, width: initialSize.width, height: initialSize.height),
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
        panel.ignoresMouseEvents = false
        panel.hidesOnDeactivate = false
        
        // Add visual effect view for glassy appearance (with click-through support)
        let visualEffectView = ClickThroughVisualEffectView()
        visualEffectView.material = .hudWindow
        visualEffectView.blendingMode = .behindWindow
        visualEffectView.state = .active
        visualEffectView.translatesAutoresizingMaskIntoConstraints = false
        
        panel.contentView = visualEffectView
        containerView = visualEffectView
        
        // Add hosting view to visual effect view
        setRootView(makeContentView())
        
        // Position in bottom-right corner
        positionPanel(panel)
        
        self.panel = panel
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
    
    /// Expands launcher into chat overlay
    func expandToChat() {
        guard let panel = panel else { return }
        guard isLauncherMode else { return }
        
        print("🔵 DEBUG: Expanding Window")
        isLauncherMode = false
        panel.styleMask = [.titled, .fullSizeContentView, .nonactivatingPanel]
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        animatePanel(panel, to: frameForMode(isLauncher: false))
        setRootView(makeContentView())
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        
        coordinator?.showChat()
    }
    
    /// Collapses chat overlay into launcher
    func collapseToLauncher() {
        guard let panel = panel else { return }
        guard !isLauncherMode else { return }
        
        isLauncherMode = true
        panel.styleMask = [.borderless, .nonactivatingPanel]
        animatePanel(panel, to: frameForMode(isLauncher: true))
        setRootView(makeContentView())
        
        coordinator?.showPopup()
    }
    
    private func makeContentView() -> AnyView {
        if isLauncherMode {
            return AnyView(
                LauncherModeView(windowManager: self)
            )
        }
        if let coordinator = coordinator {
            return AnyView(ContentView().environmentObject(coordinator))
        }
        return AnyView(EmptyView())
    }
    
    private func setRootView(_ view: AnyView) {
        guard let containerView = containerView else { return }
        containerView.subviews.forEach { $0.removeFromSuperview() }
        
        // Use click-through hosting view for first mouse support
        let hostingView = ClickThroughHostingView(rootView: view)
        hostingView.translatesAutoresizingMaskIntoConstraints = false
        containerView.addSubview(hostingView)
        
        NSLayoutConstraint.activate([
            hostingView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            hostingView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
            hostingView.topAnchor.constraint(equalTo: containerView.topAnchor),
            hostingView.bottomAnchor.constraint(equalTo: containerView.bottomAnchor)
        ])
        
        self.hostingView = hostingView
    }
    
    private func sizeForMode(isLauncher: Bool) -> CGSize {
        if isLauncher {
            return CGSize(width: 60, height: 60)
        }
        return CGSize(width: 500, height: 400)
    }
    
    private func frameForMode(isLauncher: Bool) -> NSRect {
        guard let screen = NSScreen.main else {
            let size = sizeForMode(isLauncher: isLauncher)
            return NSRect(x: 0, y: 0, width: size.width, height: size.height)
        }
        
        let screenRect = screen.visibleFrame
        let size = sizeForMode(isLauncher: isLauncher)
        let x = screenRect.maxX - size.width - 20
        let y = screenRect.minY + 20
        return NSRect(x: x, y: y, width: size.width, height: size.height)
    }
    
    private func positionPanel(_ panel: NSPanel) {
        panel.setFrame(frameForMode(isLauncher: isLauncherMode), display: false)
    }
    
    private func animatePanel(_ panel: NSPanel, to targetFrame: NSRect) {
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.3
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            panel.animator().setFrame(targetFrame, display: true)
        }
    }
}

