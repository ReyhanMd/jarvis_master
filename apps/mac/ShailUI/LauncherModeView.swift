import SwiftUI

struct LauncherModeView: View {
    @ObservedObject var windowManager: WindowManager
    @State private var isConnected: Bool = false
    
    var body: some View {
        Button(action: {
            print("🔴 DEBUG: Clicked Launcher")
            windowManager.expandToChat()
        }) {
            ZStack(alignment: .topTrailing) {
                Image(systemName: "laptopcomputer")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundColor(.blue)
                    .frame(width: 60, height: 60)
                    .background(
                        Circle()
                            .fill(Color.white.opacity(0.95))
                            .shadow(color: .black.opacity(0.2), radius: 10, x: 0, y: 5)
                    )
                
                Circle()
                    .fill(isConnected ? Color.green : Color.red)
                    .frame(width: 10, height: 10)
                    .overlay(Circle().stroke(Color.white, lineWidth: 1))
                    .offset(x: -6, y: 6)
            }
        }
        .buttonStyle(PlainButtonStyle())
        .task {
            await refreshHealth()
        }
        .onReceive(
            Timer.publish(every: 3, on: .main, in: .common).autoconnect()
        ) { _ in
            Task { await refreshHealth() }
        }
    }
    
    private func refreshHealth() async {
        guard let url = URL(string: "http://localhost:8000/health") else { return }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            if let http = response as? HTTPURLResponse {
                await MainActor.run {
                    isConnected = (200...299).contains(http.statusCode)
                }
            }
        } catch {
            await MainActor.run {
                isConnected = false
            }
        }
    }
}
