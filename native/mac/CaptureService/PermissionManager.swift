import Foundation
import AVFoundation
import CoreGraphics
import ScreenCaptureKit

class PermissionManager {
    static let shared = PermissionManager()
    
    private init() {}
    
    func checkScreenRecordingPermission() async -> Bool {
        if #available(macOS 12.3, *) {
            // Try to capture - will prompt if needed
            do {
                let _ = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                return true
            } catch {
                print("❌ Screen recording permission denied or error: \(error)")
                return false
            }
        } else {
            // Fallback for older macOS versions
            return CGPreflightScreenCaptureAccess()
        }
    }
    
    func requestScreenRecordingPermission() -> Bool {
        if #available(macOS 12.3, *) {
            // Permission is requested automatically when first accessing ScreenCaptureKit
            return true
        } else {
            return CGRequestScreenCaptureAccess()
        }
    }
}

