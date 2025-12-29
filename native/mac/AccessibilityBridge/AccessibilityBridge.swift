import Foundation
import ApplicationServices
import Cocoa

class AccessibilityBridge {
    private var server: AXWebSocketServer
    private var focusObserver: AXObserver?
    private var lastFocusedElement: AXUIElement?
    private var heartbeatTimer: Timer?
    private var eventCount: Int = 0
    
    init(server: AXWebSocketServer) {
        self.server = server
    }
    
    func startMonitoring() {
        // Monitor global focus changes
        setupGlobalFocusMonitoring()
        
        // Start heartbeat
        startHeartbeat()
        
        // Send initial state
        sendCurrentFocusInfo()
    }
    
    private func setupGlobalFocusMonitoring() {
        // Use NSWorkspace to monitor active app changes
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else {
                return
            }
            self?.handleApplicationActivated(app)
        }
        
        // Poll for focus changes (more reliable than pure observation)
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.checkFocusChange()
        }
    }
    
    private func handleApplicationActivated(_ app: NSRunningApplication) {
        guard let pid = app.processIdentifier as pid_t? else { return }
        
        let appElement = AXUIElementCreateApplication(pid)
        
        // Setup observer for this app
        setupObserverForApp(appElement, pid: pid)
        
        // Get current info
        let info = getElementInfo(appElement, appName: app.localizedName ?? "Unknown")
        sendAccessibilityEvent(info)
    }
    
    private func setupObserverForApp(_ appElement: AXUIElement, pid: pid_t) {
        var observer: AXObserver?
        
        let result = AXObserverCreate(pid, { (observer, element, notification, refcon) in
            let bridge = Unmanaged<AccessibilityBridge>.fromOpaque(refcon!).takeUnretainedValue()
            bridge.handleAccessibilityNotification(element: element, notification: notification)
        }, &observer)
        
        guard result == .success, let observer = observer else {
            print("❌ Failed to create observer for app")
            return
        }
        
        self.focusObserver = observer
        
        // Register for focus change notifications
        AXObserverAddNotification(
            observer,
            appElement,
            kAXFocusedUIElementChangedNotification as CFString,
            Unmanaged.passUnretained(self).toOpaque()
        )
        
        AXObserverAddNotification(
            observer,
            appElement,
            kAXWindowMovedNotification as CFString,
            Unmanaged.passUnretained(self).toOpaque()
        )
        
        AXObserverAddNotification(
            observer,
            appElement,
            kAXWindowResizedNotification as CFString,
            Unmanaged.passUnretained(self).toOpaque()
        )
        
        // Add observer to run loop
        CFRunLoopAddSource(
            RunLoop.main.getCFRunLoop(),
            AXObserverGetRunLoopSource(observer),
            .defaultMode
        )
    }
    
    private func handleAccessibilityNotification(element: AXUIElement, notification: CFString) {
        eventCount += 1
        
        let notificationName = notification as String
        let info = getElementInfo(element, appName: nil)
        
        var eventInfo = info
        eventInfo["notification_type"] = notificationName
        
        sendAccessibilityEvent(eventInfo)
    }
    
    private func checkFocusChange() {
        let systemWide = AXUIElementCreateSystemWide()
        var focusedElement: CFTypeRef?
        
        let result = AXUIElementCopyAttributeValue(
            systemWide,
            kAXFocusedUIElementAttribute as CFString,
            &focusedElement
        )
        
        guard result == .success, let element = focusedElement else {
            return
        }
        
        // Check if focus changed
        let currentElement = unsafeBitCast(element, to: AXUIElement.self)
        if !areElementsEqual(lastFocusedElement, currentElement) {
            lastFocusedElement = currentElement
            eventCount += 1
            
            let info = getElementInfo(currentElement, appName: nil)
            var eventInfo = info
            eventInfo["notification_type"] = "focus_changed"
            
            sendAccessibilityEvent(eventInfo)
        }
    }
    
    private func areElementsEqual(_ elem1: AXUIElement?, _ elem2: AXUIElement?) -> Bool {
        guard let e1 = elem1, let e2 = elem2 else { return false }
        return CFEqual(e1, e2)
    }
    
    private func sendCurrentFocusInfo() {
        let systemWide = AXUIElementCreateSystemWide()
        var focusedElement: CFTypeRef?
        
        let result = AXUIElementCopyAttributeValue(
            systemWide,
            kAXFocusedUIElementAttribute as CFString,
            &focusedElement
        )
        
        if result == .success, let element = focusedElement {
            let elementRef = unsafeBitCast(element, to: AXUIElement.self)
            let info = getElementInfo(elementRef, appName: nil)
            sendAccessibilityEvent(info)
        }
    }
    
    private func getElementInfo(_ element: AXUIElement, appName: String?) -> [String: Any] {
        var info: [String: Any] = [
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "element_id": UUID().uuidString
        ]
        
        // Get app name
        if let name = appName {
            info["app_name"] = name
        } else {
            var pid: pid_t = 0
            AXUIElementGetPid(element, &pid)
            if let app = NSRunningApplication(processIdentifier: pid) {
                info["app_name"] = app.localizedName ?? "Unknown"
                info["bundle_id"] = app.bundleIdentifier ?? ""
            }
        }
        
        // Get role
        if let role = getAttributeValue(element, kAXRoleAttribute as CFString) as? String {
            info["role"] = role
        }
        
        // Get title
        if let title = getAttributeValue(element, kAXTitleAttribute as CFString) as? String {
            info["title"] = title
        }
        
        // Get value/text
        if let value = getAttributeValue(element, kAXValueAttribute as CFString) {
            if let stringValue = value as? String {
                info["text"] = stringValue
            } else {
                info["value"] = String(describing: value)
            }
        }
        
        // Get description
        if let description = getAttributeValue(element, kAXDescriptionAttribute as CFString) as? String {
            info["description"] = description
        }
        
        // Get position and size
        if let positionRef = getAttributeValue(element, kAXPositionAttribute as CFString) {
            let position = unsafeBitCast(positionRef, to: AXValue.self)
            var point = CGPoint.zero
            if AXValueGetValue(position, .cgPoint, &point) {
                info["x"] = Int(point.x)
                info["y"] = Int(point.y)
            }
        }
        
        if let sizeRef = getAttributeValue(element, kAXSizeAttribute as CFString) {
            let size = unsafeBitCast(sizeRef, to: AXValue.self)
            var cgSize = CGSize.zero
            if AXValueGetValue(size, .cgSize, &cgSize) {
                info["width"] = Int(cgSize.width)
                info["height"] = Int(cgSize.height)
            }
        }
        
        // Compute bounding box if we have position and size
        if let x = info["x"] as? Int,
           let y = info["y"] as? Int,
           let width = info["width"] as? Int,
           let height = info["height"] as? Int {
            info["bbox"] = [x, y, x + width, y + height]
        }
        
        // Get window title if this is inside a window
        if let window = getWindow(for: element) {
            if let windowTitle = getAttributeValue(window, kAXTitleAttribute as CFString) as? String {
                info["window_title"] = windowTitle
            }
        }
        
        return info
    }
    
    private func getWindow(for element: AXUIElement) -> AXUIElement? {
        var parent: CFTypeRef?
        var current = element
        
        // Walk up the hierarchy to find the window
        for _ in 0..<10 {
            let result = AXUIElementCopyAttributeValue(
                current,
                kAXParentAttribute as CFString,
                &parent
            )
            
            guard result == .success, let parent = parent else {
                break
            }
            
            let parentElement = unsafeBitCast(parent, to: AXUIElement.self)
            
            // Check if this is a window
            if let role = getAttributeValue(parentElement, kAXRoleAttribute as CFString) as? String,
               role == kAXWindowRole as String {
                return parentElement
            }
            
            current = parentElement
        }
        
        return nil
    }
    
    private func getAttributeValue(_ element: AXUIElement, _ attribute: CFString) -> CFTypeRef? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        return result == .success ? value : nil
    }
    
    private func sendAccessibilityEvent(_ info: [String: Any]) {
        var eventData = info
        eventData["type"] = "accessibility_event"
        
        Task {
            await server.broadcastJSON(eventData)
        }
    }
    
    private func startHeartbeat() {
        heartbeatTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            
            let heartbeat: [String: Any] = [
                "type": "heartbeat",
                "timestamp": ISO8601DateFormatter().string(from: Date()),
                "events_captured": self.eventCount,
                "monitoring": true
            ]
            
            Task {
                await self.server.broadcastJSON(heartbeat)
            }
        }
    }
}

