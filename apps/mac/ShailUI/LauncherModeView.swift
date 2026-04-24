import SwiftUI

/// The small floating icon shown in the corner when the panel is collapsed.
/// Clicking it expands to the full Quick Popup view.
/// Shows a live status dot: green = backend up, orange = services starting, red = down.
struct LauncherModeView: View {
    @ObservedObject var windowManager: WindowManager
    @ObservedObject private var launcher = ServiceLauncher.shared

    @State private var backendAlive: Bool = false
    @State private var isHovered: Bool = false

    private var dotColor: Color {
        if backendAlive { return .green }
        if launcher.isRunning { return .orange }
        return .red
    }

    private var tooltipText: String {
        if backendAlive { return "SHAIL — Running. Click to open." }
        if launcher.isRunning { return "Starting services…" }
        if !launcher.hasValidPath { return "Repo not found — check Settings" }
        return "SHAIL — Stopped. Click to open."
    }

    var body: some View {
        Button(action: { windowManager.expandToPopup() }) {
            ZStack(alignment: .topTrailing) {
                // Main icon
                Image(systemName: "bolt.fill")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundColor(.white)
                    .frame(width: 52, height: 52)
                    .background(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [Color(hex: "#3A8DFF"), Color(hex: "#9AD0FF")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .shadow(color: Color(hex: "#3A8DFF").opacity(0.5), radius: isHovered ? 14 : 8, x: 0, y: 4)
                    )
                    .scaleEffect(isHovered ? 1.06 : 1.0)
                    .animation(.spring(response: 0.25, dampingFraction: 0.6), value: isHovered)

                // Status dot
                Circle()
                    .fill(dotColor)
                    .frame(width: 11, height: 11)
                    .overlay(Circle().stroke(Color.white, lineWidth: 1.5))
                    .offset(x: -2, y: 2)
                    // Pulse when starting
                    .opacity(launcher.isRunning && !backendAlive ? pulsingOpacity : 1.0)
            }
        }
        .buttonStyle(PlainButtonStyle())
        .help(tooltipText)
        .onHover { isHovered = $0 }
        .task { await checkBackend() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            Task { await checkBackend() }
        }
        .onAppear {
            startPulse()
            if !launcher.isRunning && launcher.hasValidPath {
                launcher.startAll()
            }
        }
    }

    // Animating pulsing opacity for "starting" state
    @State private var pulsingOpacity: Double = 1.0
    private func startPulse() {
        withAnimation(Animation.easeInOut(duration: 0.7).repeatForever(autoreverses: true)) {
            pulsingOpacity = 0.3
        }
    }

    private func checkBackend() async {
        guard let url = URL(string: "http://localhost:8000/health") else { return }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            let alive = (response as? HTTPURLResponse).map { (200...299).contains($0.statusCode) } ?? false
            await MainActor.run { backendAlive = alive }
        } catch {
            await MainActor.run { backendAlive = false }
        }
    }
}

// MARK: - Color hex helper

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let r, g, b: Double
        switch hex.count {
        case 6:
            (r, g, b) = (Double((int >> 16) & 0xFF) / 255,
                         Double((int >> 8)  & 0xFF) / 255,
                         Double(int & 0xFF)          / 255)
        default:
            (r, g, b) = (1, 1, 1)
        }
        self.init(red: r, green: g, blue: b)
    }
}
