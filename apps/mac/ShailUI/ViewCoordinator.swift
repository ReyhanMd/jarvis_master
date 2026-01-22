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
    @Published var selectedNodeId: String? = nil // Selected node from graph
    @Published var selectedNodeState: GraphState? = nil // State for selected node
    @Published var activeTaskId: String? = nil // Task ID for result view
    var collapseToLauncher: (() -> Void)? = nil
    
    // Navigation functions
    func showPopup() {
        withAnimation { currentView = .popup }
    }
    
    func showChat() {
        withAnimation { currentView = .chat }
    }
    
    func showDetail(desktopId: String? = nil, nodeId: String? = nil) {
        if let desktopId = desktopId {
            activeDesktop = desktopId
        }
        if let nodeId = nodeId {
            selectedNodeId = nodeId
        }
        withAnimation { currentView = .detail }
    }
    
    func showBirdsEye() {
        withAnimation { currentView = .birdsEye }
    }
}
