import Foundation
import ApplicationServices

@main
struct AccessibilityBridgeMain {
    static func main() {
        print("♿ AccessibilityBridge initializing...")
        print("📍 Check this console for all output!")
        fflush(stdout)
        
        // Keep app alive
        let group = DispatchGroup()
        group.enter()
        
        // Launch async work
        Task.detached {
            await Self.launch()
        }
        
        print("⏳ App running... waiting for events")
        fflush(stdout)
        
        RunLoop.main.run()
    }
    
    static func launch() async {
        print("📌 Requesting Accessibility permission...")
        fflush(stdout)
        
        // Check permission
        let allowed = AXPermissionManager.shared.checkAccessibilityPermission()
        if !allowed {
            print("⚠️  Accessibility permission required!")
            print("   Requesting permission...")
            fflush(stdout)
            
            AXPermissionManager.shared.requestAccessibilityPermission()
            
            print("   1. macOS should show a permission dialog")
            print("   2. Click 'Open System Settings'")
            print("   3. Enable 'AccessibilityBridge'")
            print("   4. Restart this app")
            fflush(stdout)
            
            // Keep alive for 15 seconds
            try? await Task.sleep(nanoseconds: 15_000_000_000)
            return
        }
        
        print("✅ Accessibility permission granted!")
        fflush(stdout)
        
        // Start health check server
        print("🏥 Starting health check server on port 8768...")
        fflush(stdout)
        let healthServer = AXHealthCheckServer(port: 8768)
        await healthServer.start()
        
        // Start WebSocket server
        print("🌐 Starting WebSocket server on port 8766...")
        fflush(stdout)
        let ws = AXWebSocketServer(port: 8766)
        await ws.start()
        
        // Start accessibility monitoring
        print("📡 Starting accessibility monitoring...")
        fflush(stdout)
        let bridge = AccessibilityBridge(server: ws)
        bridge.startMonitoring()
        
        print("🟢 AccessibilityBridge LIVE at ws://localhost:8766/accessibility")
        print("🏥 Health check available at http://localhost:8768/health")
        print("📊 Monitoring focus changes and window events")
        print("💡 App will run until you press Stop in Xcode")
        fflush(stdout)
    }
}
