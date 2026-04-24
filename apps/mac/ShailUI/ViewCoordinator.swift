import SwiftUI

enum ShailViewMode {
    case popup
    case chat
    case detail
    case birdsEye
    case offlineDashboard
}

class ViewCoordinator: ObservableObject {
    @Published var currentView:       ShailViewMode  = .popup
    @Published var messages:          [ChatMessage]  = []
    @Published var lastChatResponse:  String?
    @Published var activeDesktop:     String?
    @Published var selectedNodeId:    String?
    @Published var selectedNodeState: GraphState?
    @Published var activeTaskId:      String?
    @Published var hasError: Bool = false
    var collapseToLauncher: (() -> Void)?
    var expandToOfflineDashboard: (() -> Void)?
    var hidePanel: (() -> Void)?
    var openBirdsEyeWindow: (() -> Void)?
    var resetToPopupSize: (() -> Void)?

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
        openBirdsEyeWindow?()
    }

    func showOfflineDashboard() {
        hasError = true
        expandToOfflineDashboard?()
        withAnimation { currentView = .offlineDashboard }
    }
}
