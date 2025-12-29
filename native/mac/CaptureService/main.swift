import Foundation
import ScreenCaptureKit

@main
struct CaptureServiceMain {
    static func main() {
        print("🎥 CaptureService initializing...")
        print("📍 Check this console for all output!")
        
        // Force console output to flush
        fflush(stdout)
        
        // Create a dispatch group to keep app alive
        let group = DispatchGroup()
        group.enter() // Never leave - keeps app alive
        
        // Launch async work
        Task.detached {
            await Self.launch()
        }
        
        // Block forever - keeps app running
        print("⏳ App running... waiting for events")
        fflush(stdout)
        
        RunLoop.main.run()
    }
    
    static func launch() async {
        print("📌 Checking Screen Recording permission...")
        fflush(stdout)
        
        // Retry logic for permission check (macOS sometimes needs a moment)
        var permissionGranted = false
        let maxRetries = 5
        var retryCount = 0
        
        while !permissionGranted && retryCount < maxRetries {
            do {
                _ = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                permissionGranted = true
                print("✅ Screen recording permission GRANTED!")
                fflush(stdout)
                break
            } catch {
                let errorCode = (error as NSError).code
                let errorDomain = (error as NSError).domain
                
                // Error -3801 means permission was declined/not granted
                if errorDomain == "com.apple.ScreenCaptureKit.SCStreamErrorDomain" && errorCode == -3801 {
                    retryCount += 1
                    
                    if retryCount < maxRetries {
                        print("⏳ Permission check failed (attempt \(retryCount)/\(maxRetries))...")
                        print("   Waiting 2 seconds before retry...")
                        print("   💡 If you just enabled permission, macOS may need a moment to apply it.")
                        fflush(stdout)
                        try? await Task.sleep(nanoseconds: 2_000_000_000) // Wait 2 seconds
                    } else {
                        print("❌ Permission error after \(maxRetries) attempts: \(error)")
                        print("")
                        print("⚠️  TROUBLESHOOTING STEPS:")
                        print("   1. Open System Settings → Privacy & Security → Screen Recording")
                        print("   2. Make sure 'CaptureService' is listed and toggle is ON (blue)")
                        print("   3. If CaptureService is NOT in the list:")
                        print("      - Click the '+' button")
                        print("      - Navigate to: ~/Library/Developer/Xcode/DerivedData/")
                        print("      - Find CaptureService.app and add it")
                        print("   4. QUIT this app completely (⌘+Q in Xcode)")
                        print("   5. Rebuild and run again")
                        print("")
                        print("   Current bundle ID: com.shail.CaptureService")
                        fflush(stdout)
                        
                        // Keep app alive for 20 seconds to read message
                        try? await Task.sleep(nanoseconds: 20_000_000_000)
                        return
                    }
                } else {
                    // Different error - log and exit
                    print("❌ Unexpected permission error: \(error)")
                    print("   Error code: \(errorCode), Domain: \(errorDomain)")
                    fflush(stdout)
                    try? await Task.sleep(nanoseconds: 10_000_000_000)
                    return
                }
            }
        }
        
        if !permissionGranted {
            print("❌ Failed to obtain permission after \(maxRetries) attempts")
            fflush(stdout)
            return
        }
        
        // Start health check server
        print("🏥 Starting health check server on port 8767...")
        fflush(stdout)
        let healthServer = HealthCheckServer(port: 8767)
        await healthServer.start()
        
        // Start WebSocket server
        print("🌐 Starting WebSocket server on port 8765...")
        fflush(stdout)
        let ws = WebSocketServer(port: 8765)
        await ws.start()
        
        // Start screen capture
        print("📹 Starting screen capture...")
        fflush(stdout)
        let capturer = ScreenCaptureService()
        await capturer.start(streamer: ws)
        
        print("🟢 CaptureService LIVE at ws://localhost:8765/capture")
        print("🏥 Health check available at http://localhost:8767/health")
        print("📊 Streaming at 30 FPS with JPEG compression")
        print("💡 App will run until you press Stop in Xcode")
        fflush(stdout)
    }
}
