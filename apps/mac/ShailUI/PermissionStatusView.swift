import SwiftUI
import AppKit

/// Permission status information
struct PermissionStatus {
    let name: String
    let isGranted: Bool
    let settingsURL: URL?
}

/// View that displays permission status badges
struct PermissionStatusView: View {
    @State private var screenRecordingStatus: PermissionStatus?
    @State private var accessibilityStatus: PermissionStatus?
    @State private var inputMonitoringStatus: PermissionStatus?
    @State private var nativeHealth: NativeHealthStatus?
    
    var body: some View {
        HStack(spacing: 8) {
            if let screenRecording = screenRecordingStatus {
                PermissionBadge(status: screenRecording)
            }
            if let accessibility = accessibilityStatus {
                PermissionBadge(status: accessibility)
            }
            if let inputMonitoring = inputMonitoringStatus {
                PermissionBadge(status: inputMonitoring)
            }
            if let health = nativeHealth {
                PermissionBadge(
                    status: PermissionStatus(
                        name: "Grounding",
                        isGranted: health.capture == "connected" && health.accessibility == "connected",
                        settingsURL: nil
                    )
                )
            }
            Button(action: {
                checkPermissions()
            }) {
                Image(systemName: "arrow.clockwise")
                    .font(.caption)
            }
            .buttonStyle(PlainButtonStyle())
            .help("Refresh permission and connection status")
        }
        .onAppear {
            checkPermissions()
        }
    }
    
    private func checkPermissions() {
        // Check Screen Recording permission
        screenRecordingStatus = PermissionStatus(
            name: "Screen",
            isGranted: checkScreenRecordingPermission(),
            settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
        )
        
        // Check Accessibility permission
        accessibilityStatus = PermissionStatus(
            name: "Accessibility",
            isGranted: checkAccessibilityPermission(),
            settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        )
        
        // Check Input Monitoring permission (for hotkeys)
        inputMonitoringStatus = PermissionStatus(
            name: "Input",
            isGranted: checkInputMonitoringPermission(),
            settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
        )

        Task {
            await checkNativeHealth()
        }
    }
    
    private func checkScreenRecordingPermission() -> Bool {
        if #available(macOS 10.15, *) {
            return CGPreflightScreenCaptureAccess()
        }
        return CGPreflightScreenCaptureAccess()
    }
    
    private func checkAccessibilityPermission() -> Bool {
        // Check Accessibility permission
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: false]
        return AXIsProcessTrustedWithOptions(options as CFDictionary)
    }
    
    private func checkInputMonitoringPermission() -> Bool {
        // Input Monitoring permission check
        // This is harder to check directly, so we'll try to use it and see if it works
        // For now, return true as a placeholder
        return true
    }

    private func checkNativeHealth() async {
        guard let url = URL(string: "http://localhost:8000/health/native") else { return }
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                return
            }
            let decoded = try JSONDecoder().decode(NativeHealthStatus.self, from: data)
            await MainActor.run {
                nativeHealth = decoded
            }
        } catch {
            // ignore
        }
    }
}

/// Individual permission badge
struct PermissionBadge: View {
    let status: PermissionStatus
    
    var body: some View {
        Button(action: {
            if !status.isGranted, let url = status.settingsURL {
                NSWorkspace.shared.open(url)
            }
        }) {
            HStack(spacing: 4) {
                Image(systemName: status.isGranted ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundColor(status.isGranted ? .green : .orange)
                    .font(.caption)
                Text(status.name)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(status.isGranted ? Color.green.opacity(0.1) : Color.orange.opacity(0.1))
            .cornerRadius(8)
        }
        .buttonStyle(PlainButtonStyle())
        .help(status.isGranted ? "\(status.name) permission granted" : "Click to open System Settings")
    }
}

