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

class AppDelegate: NSObject, NSApplicationDelegate {
    var windowManager: WindowManager?
    let coordinator = ViewCoordinator()
    var hotkeyListener: GlobalInputListener?

    // Menubar
    private var statusItem: NSStatusItem?
    private var startMenuItem: NSMenuItem?
    private var stopMenuItem: NSMenuItem?

    // Bird's Eye standalone window
    private var birdsEyeWindow: NSWindow?
    private var birdsEyeHostingController: NSViewController?
    private var birdsEyeWindowDelegate: BirdsEyeWindowDelegate?

    private let launcher = ServiceLauncher.shared
    private var launcherObserver: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenubar()
        setupFloatingPanel()
        observeLauncherState()
        BackendManager.shared.startMonitoring()
        NSApp.setActivationPolicy(.accessory)
    }

    func applicationWillTerminate(_ notification: Notification) {
        hotkeyListener?.stopMonitoring()
        BackendManager.shared.stopMonitoring()
        launcher.stopAll()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        windowManager?.show()
        return true
    }

    // MARK: - Menubar

    private func setupMenubar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        updateMenubarIcon(running: false)

        let menu = NSMenu()

        let showItem = NSMenuItem(title: "Show SHAIL  ⌘⇧S", action: #selector(showPanel), keyEquivalent: "")
        menu.addItem(showItem)

        menu.addItem(NSMenuItem.separator())

        let startItem = NSMenuItem(title: "Start Services", action: #selector(startServices), keyEquivalent: "")
        startMenuItem = startItem
        menu.addItem(startItem)

        let stopItem = NSMenuItem(title: "Stop Services", action: #selector(stopServices), keyEquivalent: "")
        stopItem.isEnabled = false
        stopMenuItem = stopItem
        menu.addItem(stopItem)

        menu.addItem(NSMenuItem.separator())

        let configItem = NSMenuItem(title: "Configure Repo Path…", action: #selector(configureRepoPath), keyEquivalent: "")
        menu.addItem(configItem)

        menu.addItem(NSMenuItem.separator())

        menu.addItem(NSMenuItem(title: "Quit SHAIL", action: #selector(quitApp), keyEquivalent: "q"))

        statusItem?.menu = menu
    }

    private func updateMenubarIcon(running: Bool) {
        if let button = statusItem?.button {
            let symbolName = running ? "bolt.fill" : "bolt"
            let config = NSImage.SymbolConfiguration(pointSize: 14, weight: .medium)
            button.image = NSImage(systemSymbolName: symbolName, accessibilityDescription: "SHAIL")?
                .withSymbolConfiguration(config)
            button.toolTip = running ? "SHAIL — Running" : "SHAIL — Stopped"
        }
    }

    private func observeLauncherState() {
        launcherObserver = NotificationCenter.default.addObserver(
            forName: .init("ShailLauncherStateChanged"),
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.syncMenubarToLauncherState()
        }

        Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            DispatchQueue.main.async { self?.syncMenubarToLauncherState() }
        }
    }

    private func syncMenubarToLauncherState() {
        let running = launcher.isRunning
        updateMenubarIcon(running: running)
        startMenuItem?.isEnabled = !running
        stopMenuItem?.isEnabled = running
    }

    // MARK: - Panel

    private func setupFloatingPanel() {
        windowManager = WindowManager()
        windowManager?.createPanel(coordinator: coordinator, startInLauncher: false)
        coordinator.collapseToLauncher = { [weak self] in
            self?.windowManager?.collapseToLauncher()
        }
        coordinator.expandToOfflineDashboard = { [weak self] in
            self?.windowManager?.showOfflineDashboard()
        }
        coordinator.hidePanel = { [weak self] in
            self?.windowManager?.hide()
        }
        coordinator.resetToPopupSize = { [weak self] in
            self?.windowManager?.showAsPopup()
        }
        coordinator.openBirdsEyeWindow = { [weak self] in
            self?.openBirdsEyeWindow()
        }
        windowManager?.showAsPopup()
    }

    // MARK: - Bird's Eye Standalone Window

    func openBirdsEyeWindow() {
        // Bring existing window forward if still alive
        if let existing = birdsEyeWindow {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let screen = NSScreen.main ?? NSScreen.screens[0]
        let sw = screen.visibleFrame.width
        let sh = screen.visibleFrame.height
        let w: CGFloat = min(1100, sw * 0.82)
        let h: CGFloat = min(740, sh * 0.82)
        let x = screen.visibleFrame.midX - w / 2
        let y = screen.visibleFrame.midY - h / 2

        let window = NSWindow(
            contentRect: NSRect(x: x, y: y, width: w, height: h),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "SHAIL — Bird's Eye Workflow"
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        window.backgroundColor = NSColor(red: 0.04, green: 0.04, blue: 0.09, alpha: 1)
        window.minSize = NSSize(width: 700, height: 500)
        // Prevent NSWindow from releasing itself on close — avoids EXC_BAD_ACCESS on reopen
        window.isReleasedWhenClosed = false

        let rootView = BirdsEyeView()
            .environmentObject(coordinator)
            .environmentObject(BackendManager.shared)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: NSColor(red: 0.04, green: 0.04, blue: 0.09, alpha: 1)))

        let hc = NSHostingController(rootView: rootView)
        window.contentViewController = hc

        // Nil out reference when window closes so reopen creates a fresh window
        let delegate = BirdsEyeWindowDelegate { [weak self] in
            self?.birdsEyeWindow = nil
            self?.birdsEyeWindowDelegate = nil
            self?.birdsEyeHostingController = nil
        }
        window.delegate = delegate
        birdsEyeWindowDelegate = delegate

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        birdsEyeWindow = window
        birdsEyeHostingController = hc
    }

    // MARK: - Actions

    @objc private func showPanel() {
        windowManager?.show()
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func startServices() {
        launcher.startAll()
    }

    @objc private func stopServices() {
        launcher.stopAll()
    }

    @objc private func configureRepoPath() {
        launcher.promptForRepoPath()
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}

// MARK: - Window delegate that fires a callback on close

private class BirdsEyeWindowDelegate: NSObject, NSWindowDelegate {
    private let onClose: () -> Void
    init(onClose: @escaping () -> Void) { self.onClose = onClose }
    func windowWillClose(_ notification: Notification) { onClose() }
}
