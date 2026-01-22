import Cocoa

@main
class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private let launchManager = LaunchManager()

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupStatusItem()
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.title = "Shail"
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Start Shail", action: #selector(startShail), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(title: "Stop Shail", action: #selector(stopShail), keyEquivalent: "q"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: ""))
        statusItem?.menu = menu
    }

    @objc private func startShail() {
        launchManager.startAll()
    }

    @objc private func stopShail() {
        launchManager.stopAll()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
