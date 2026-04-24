import SwiftUI
import WebKit

enum BirdsEyeDashboard: String, CaseIterable {
    case langGraph = "LangGraph"
    case memory    = "Memory"

    var icon: String {
        switch self {
        case .langGraph: return "network"
        case .memory:    return "brain"
        }
    }
}

struct BirdsEyeView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @EnvironmentObject var backendManager: BackendManager
    @StateObject private var wsClient = BackendWebSocketClient()
    @State private var selectedNodeId: String?
    @State private var activePanel: BirdsEyeDashboard = .langGraph

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider()
            contentPanel
        }
        .frame(minWidth: 1000, minHeight: 700)
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("SHAIL")
                .font(.headline)
                .padding(.bottom, 4)

            HStack(spacing: 6) {
                Circle()
                    .fill(wsClient.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text(wsClient.isConnected ? "Connected" : "Disconnected")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Divider().padding(.vertical, 12)

            // Dashboard toggle buttons
            VStack(alignment: .leading, spacing: 2) {
                ForEach(BirdsEyeDashboard.allCases, id: \.self) { panel in
                    dashboardButton(panel)
                }
            }

            // LangGraph state detail (shown only when LangGraph tab active)
            if activePanel == .langGraph {
                if let state = wsClient.currentState {
                    Divider().padding(.vertical, 10)
                    langGraphDetail(state)
                }
            }

            Spacer()

            if !backendManager.isAvailable {
                Label("Demo mode — no backend", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundColor(.orange)
                    .padding(.bottom, 4)
                Button("Fix API Key →") { coordinator.showPopup() }
                    .font(.caption)
                    .foregroundColor(.orange)
                    .buttonStyle(.plain)
                    .padding(.bottom, 8)
            }

            Button(action: { coordinator.showPopup() }) {
                HStack {
                    Image(systemName: "xmark.circle")
                    Text("Close")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
        }
        .padding()
        .frame(width: 260)
        .background(Color.gray.opacity(0.08))
    }

    private func dashboardButton(_ panel: BirdsEyeDashboard) -> some View {
        Button(action: { withAnimation(.easeInOut(duration: 0.2)) { activePanel = panel } }) {
            HStack(spacing: 10) {
                Image(systemName: panel.icon)
                    .frame(width: 16)
                Text(panel.rawValue)
                    .fontWeight(activePanel == panel ? .semibold : .regular)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(activePanel == panel ? Color.accentColor.opacity(0.18) : Color.clear)
            .cornerRadius(8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundColor(activePanel == panel ? .accentColor : .primary)
    }

    @ViewBuilder
    private func langGraphDetail(_ state: GraphState) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Status: \(state.status)")
                .font(.caption).fontWeight(.bold)
            Text("Node: \(state.currentNode)")
                .font(.caption2)
            Text("Step: \(state.currentStepIndex + 1)/\(state.stepCount)")
                .font(.caption2)
            if let error = state.error {
                Text("Error: \(error)")
                    .font(.caption2).foregroundColor(.red)
            }
        }

        if let nodeId = selectedNodeId {
            Divider().padding(.vertical, 6)
            Text("Selected")
                .font(.caption2).fontWeight(.semibold).foregroundColor(.secondary)
            Text(nodeId.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.caption2)
        }

        if !state.planSteps.isEmpty {
            Divider().padding(.vertical, 6)
            Text("Plan Steps")
                .font(.caption).fontWeight(.semibold)
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(state.planSteps.enumerated()), id: \.element.stepId) { index, step in
                        HStack(spacing: 6) {
                            Circle().fill(stepColor(step)).frame(width: 6, height: 6)
                            Text("\(index + 1). \(step.description)")
                                .font(.caption2).lineLimit(1)
                        }
                    }
                }
            }
            .frame(maxHeight: 180)
        }
    }

    // MARK: - Content Panel

    @ViewBuilder
    private var contentPanel: some View {
        switch activePanel {
        case .langGraph:
            graphContent
        case .memory:
            memoryContent
        }
    }

    private var graphContent: some View {
        ZStack {
            GraphWebView(
                graphState: Binding(get: { wsClient.currentState }, set: { _ in }),
                onNodeClick: { nodeId in
                    selectedNodeId = nodeId
                    coordinator.selectedNodeId = nodeId
                }
            )
            if wsClient.currentState == nil {
                VStack(spacing: 10) {
                    Image(systemName: "brain.head.profile")
                        .font(.system(size: 60))
                        .foregroundColor(.gray)
                    Text(backendManager.isAvailable && !coordinator.hasError
                         ? "Waiting for LangGraph state..."
                         : "Showing demo workflow")
                        .font(.headline).foregroundColor(.gray)
                    if !backendManager.isAvailable || coordinator.hasError {
                        Text("Fix your API key in the sidebar to go live")
                            .font(.caption).foregroundColor(.orange)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .windowBackgroundColor).opacity(0.9))
            }
        }
        .onAppear {
            wsClient.connect()
            if !backendManager.isAvailable || coordinator.hasError {
                wsClient.currentState = MockDataProvider.demoGraphState
            }
        }
    }

    private var memoryContent: some View {
        MemoryDashboardWebView(
            urlString: "\(SettingsManager.shared.settings.api.baseURL)/dashboard",
            apiKey: SettingsManager.shared.settings.apiKey
        )
    }

    func stepColor(_ step: PlanStep) -> Color {
        if let success = step.success { return success ? .green : .red }
        return step.executed ? .blue : .gray
    }
}

struct MemoryDashboardWebView: NSViewRepresentable {
    let urlString: String
    let apiKey: String

    func makeNSView(context: Context) -> WKWebView {
        let wv = WKWebView(frame: .zero)
        if let url = URL(string: urlString) {
            var req = URLRequest(url: url)
            if !apiKey.isEmpty { req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization") }
            wv.load(req)
        }
        return wv
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
