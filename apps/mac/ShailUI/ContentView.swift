import SwiftUI

struct ContentView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    
    var body: some View {
        ZStack {
            switch coordinator.currentView {
            case .popup:
                QuickPopupView()
                    .transition(.opacity)
            case .chat:
                ChatOverlayView()
                    .transition(.opacity)
            case .detail:
                DetailView()
                    .transition(.move(edge: .trailing))
            case .birdsEye:
                BirdsEyeView()
                    .transition(.scale)
            case .offlineDashboard:
                OfflineDashboardView()
                    .transition(.scale)
            }
        }
        .animation(.easeInOut, value: coordinator.currentView)
    }
}
