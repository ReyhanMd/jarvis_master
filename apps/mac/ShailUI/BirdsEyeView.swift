import SwiftUI

struct BirdsEyeView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @StateObject private var wsClient = BackendWebSocketClient()
    @State private var selectedNodeId: String?
    
    var body: some View {
        HStack(spacing: 0) {
            // Dataset/Log Panel (Sidebar)
            VStack(alignment: .leading) {
                Text("LangGraph State")
                    .font(.headline)
                    .padding(.bottom)
                
                // Connection Status
                HStack {
                    Circle()
                        .fill(wsClient.isConnected ? Color.green : Color.red)
                        .frame(width: 8, height: 8)
                    Text(wsClient.isConnected ? "Connected" : "Disconnected")
                        .font(.caption)
                }
                .padding(.bottom)
                
                // Current State Info
                if let state = wsClient.currentState {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Status: \(state.status)")
                            .font(.caption)
                            .fontWeight(.bold)
                        
                        Text("Current Node: \(state.currentNode)")
                            .font(.caption2)
                        
                        Text("Step: \(state.currentStepIndex + 1)/\(state.stepCount)")
                            .font(.caption2)
                        
                        if let error = state.error {
                            Text("Error: \(error)")
                                .font(.caption2)
                                .foregroundColor(.red)
                        }
                    }
                    .padding(.bottom)
                }
                
                // Selected Node Info
                if let nodeId = selectedNodeId, let state = wsClient.currentState {
                    Divider()
                        .padding(.vertical, 8)
                    
                    Text("Selected Node")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                    
                    Text(nodeId.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption)
                        .padding(.bottom, 4)
                    
                    // Show related plan steps for this node
                    if nodeId == "execute_step" || nodeId.contains("execute") {
                        if !state.planSteps.isEmpty {
                            Text("Related Steps:")
                                .font(.caption2)
                                .fontWeight(.semibold)
                                .padding(.top, 4)
                            
                            ScrollView {
                                VStack(alignment: .leading, spacing: 4) {
                                    ForEach(Array(state.planSteps.enumerated()), id: \.element.stepId) { index, step in
                                        HStack {
                                            Circle()
                                                .fill(stepColor(step))
                                                .frame(width: 6, height: 6)
                                            Text("\(index + 1). \(step.description)")
                                                .font(.caption2)
                                                .lineLimit(2)
                                        }
                                    }
                                }
                            }
                            .frame(maxHeight: 200)
                        }
                    }
                }
                
                // Plan Steps
                if let state = wsClient.currentState, !state.planSteps.isEmpty {
                    Divider()
                        .padding(.vertical, 8)
                    
                    Text("Plan Steps")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .padding(.top)
                    
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(state.planSteps.enumerated()), id: \.element.stepId) { index, step in
                                HStack {
                                    Circle()
                                        .fill(stepColor(step))
                                        .frame(width: 6, height: 6)
                                    Text("\(index + 1). \(step.description)")
                                        .font(.caption2)
                                        .lineLimit(1)
                                }
                            }
                        }
                    }
                }
                
                Spacer()
                
                // Action buttons
                VStack(spacing: 8) {
                    Button(action: {
                        coordinator.showDetail(nodeId: selectedNodeId ?? "master")
                    }) {
                        HStack {
                            Image(systemName: "info.circle")
                            Text("View Details")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(selectedNodeId == nil)
                    
                    Button(action: {
                        coordinator.showPopup()
                    }) {
                        HStack {
                            Image(systemName: "xmark.circle")
                            Text("Close")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.top)
            }
            .padding()
            .frame(width: 280)
            .background(Color.gray.opacity(0.1))
            
            // React Flow Graph WebView
            ZStack {
                GraphWebView(
                    graphState: Binding(
                        get: { wsClient.currentState },
                        set: { _ in }
                    ),
                    onNodeClick: { nodeId in
                        selectedNodeId = nodeId
                        coordinator.selectedNodeId = nodeId
                    }
                )
                
                // Empty state overlay
                if wsClient.currentState == nil {
            VStack {
                        Image(systemName: "brain.head.profile")
                            .font(.system(size: 60))
                            .foregroundColor(.gray)
                        Text("Waiting for LangGraph state...")
                            .font(.headline)
                            .foregroundColor(.gray)
                        if !wsClient.isConnected {
                            Text("Not connected to backend")
                                .font(.caption)
                                .foregroundColor(.red)
                                .padding(.top, 4)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color.white.opacity(0.9))
                }
            }
            .onAppear {
                wsClient.connect()
            }
        }
        .frame(minWidth: 1000, minHeight: 700)
    }
    
    func stepColor(_ step: PlanStep) -> Color {
        if let success = step.success {
            return success ? .green : .red
        }
        return step.executed ? .blue : .gray
    }
}
