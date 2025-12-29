import SwiftUI

enum ShailViewMode {
    case popup
    case chat
    case detail
    case birdsEye
}

class ViewCoordinator: ObservableObject {
    @Published var currentView: ShailViewMode = .popup
    @Published var activeDesktop: String? = nil // For DetailView to know which "desktop" to show
    @Published var lastChatResponse: String? = nil // Store last chat response
    
    // Navigation functions
    func showPopup() {
        withAnimation { currentView = .popup }
    }
    
    func showChat() {
        withAnimation { currentView = .chat }
    }
    
    func showDetail(desktopId: String) {
        activeDesktop = desktopId
        withAnimation { currentView = .detail }
    }
    
    func showBirdsEye() {
        withAnimation { currentView = .birdsEye }
    }
}
