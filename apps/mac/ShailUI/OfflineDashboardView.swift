import SwiftUI

struct OfflineDashboardView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @EnvironmentObject var backendManager: BackendManager

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                // Mini header bar so user knows where they are
                HStack {
                    Image(systemName: "bolt.fill")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(ShailTheme.primaryGradient)
                    Text("SHAIL")
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .foregroundColor(.white.opacity(0.85))
                    Spacer()
                    Button { coordinator.showPopup() } label: {
                        Image(systemName: "arrow.uturn.backward")
                            .font(.system(size: 11))
                            .foregroundColor(.white.opacity(0.45))
                    }
                    .buttonStyle(.plain)
                    .help("Back to Quick Popup")
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.white.opacity(0.06))

                ChatOverlayView()
            }
            .frame(width: 340)
            .background(ShailTheme.glassBackground())

            Divider()
                .background(Color.white.opacity(0.12))

            BirdsEyeView()
        }
    }
}
