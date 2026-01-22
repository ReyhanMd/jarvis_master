import AppKit
import SwiftUI

final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    
    /// Enable click-through: accept first mouse click even when app is in background
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        return true
    }
}

/// Custom NSVisualEffectView that accepts first mouse for click-through
class ClickThroughVisualEffectView: NSVisualEffectView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        return true
    }
}

/// Custom NSHostingView that accepts first mouse for click-through
class ClickThroughHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        return true
    }
}
