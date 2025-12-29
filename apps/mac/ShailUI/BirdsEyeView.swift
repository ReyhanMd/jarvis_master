import SwiftUI

struct BirdsEyeView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @StateObject private var wsClient = BackendWebSocketClient()
    
    // Workflow Nodes (dynamically updated from WebSocket)
    struct WorkflowNode: Identifiable {
        let id: String
        let name: String
        let type: String // Master, Sub, Software, Action, Verification
        let position: CGPoint
        let status: String // active, completed, failed, pending
    }
    
    @State private var nodes: [WorkflowNode] = []
    @State private var currentState: GraphState?
    
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
                
                // Plan Steps
                if let state = wsClient.currentState, !state.planSteps.isEmpty {
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
            }
            .padding()
            .frame(width: 250)
            .background(Color.gray.opacity(0.1))
            
            // Workflow Graph
            ZStack {
                Color.white
                
                // Draw Edges (based on graph state)
                if let state = wsClient.currentState, !state.edges.isEmpty {
                    // Use edges from state
                    Path { path in
                        for edge in state.edges {
                            // Find nodes by ID
                            if let fromNode = nodes.first(where: { $0.id == edge.from }),
                               let toNode = nodes.first(where: { $0.id == edge.to }) {
                                path.move(to: fromNode.position)
                                path.addLine(to: toNode.position)
                            }
                        }
                    }
                    .stroke(Color.gray.opacity(0.3), lineWidth: 2)
                } else if !nodes.isEmpty {
                    // Fallback: draw edges between sequential nodes
                    Path { path in
                        for i in 0..<nodes.count - 1 {
                            let from = nodes[i]
                            let to = nodes[i + 1]
                            path.move(to: from.position)
                            path.addLine(to: to.position)
                        }
                    }
                    .stroke(Color.gray, lineWidth: 2)
                }
                
                // Nodes (dynamically generated from state)
                ForEach(nodes) { node in
                    VStack {
                        Image(systemName: iconForType(node.type))
                            .font(.title)
                            .foregroundColor(.white)
                            .frame(width: 50, height: 50)
                            .background(nodeColor(node))
                            .clipShape(Circle())
                            .overlay(
                                Circle()
                                    .stroke(node.status == "active" ? Color.yellow : Color.clear, lineWidth: 3)
                            )
                        
                        Text(node.name)
                            .font(.caption)
                            .fontWeight(.bold)
                    }
                    .position(node.position)
                    .onTapGesture {
                        if node.type == "Software" || node.type == "Sub" {
                            coordinator.showDetail(desktopId: node.name)
                        }
                    }
                }
                
                // Empty state
                if nodes.isEmpty {
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
                        }
                    }
                }
            }
            .onAppear {
                wsClient.connect()
                updateNodesFromState()
            }
            .onChange(of: wsClient.currentState) { _ in
                updateNodesFromState()
            }
            .gesture(DragGesture().onEnded { value in
                // "Swipe up/down" or pinch to exit?
                // Let's say we just have a button for now
            })
            
            // Interaction overlay
            VStack {
                HStack {
                    Spacer()
                    Button(action: { coordinator.showPopup() }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title)
                            .foregroundColor(.gray)
                    }
                    .padding()
                }
                Spacer()
            }
        }
        .frame(minWidth: 800, minHeight: 600)
    }
    
    func iconForType(_ type: String) -> String {
        switch type {
            case "Master": return "brain.head.profile"
            case "Sub": return "person.fill.viewfinder"
            case "Software": return "macwindow"
            default: return "circle"
        }
    }
    
    func colorForType(_ type: String) -> Color {
        switch type {
            case "Master": return .purple
            case "Sub": return .blue
            case "Software": return .orange
            case "Action": return .green
            case "Verification": return .cyan
            default: return .gray
        }
    }
    
    func nodeColor(_ node: WorkflowNode) -> Color {
        let baseColor = colorForType(node.type)
        switch node.status {
        case "completed":
            return baseColor.opacity(0.7)
        case "failed":
            return .red
        case "active":
            return baseColor
        default:
            return baseColor.opacity(0.5)
        }
    }
    
    func stepColor(_ step: PlanStep) -> Color {
        if let success = step.success {
            return success ? .green : .red
        }
        return step.executed ? .blue : .gray
    }
    
    func updateNodesFromState() {
        guard let state = wsClient.currentState else {
            // Use default nodes if no state
            if nodes.isEmpty {
                nodes = [
                    WorkflowNode(id: "master", name: "Master Planner", type: "Master", position: CGPoint(x: 400, y: 100), status: "pending"),
                    WorkflowNode(id: "generate", name: "Generate Plan", type: "Action", position: CGPoint(x: 200, y: 250), status: "pending"),
                    WorkflowNode(id: "execute", name: "Execute Steps", type: "Action", position: CGPoint(x: 400, y: 250), status: "pending"),
                    WorkflowNode(id: "verify", name: "Verify", type: "Verification", position: CGPoint(x: 600, y: 250), status: "pending")
                ]
            }
            return
        }
        
        // Generate nodes from LangGraph state
        var newNodes: [WorkflowNode] = []
        
        // Master node
        newNodes.append(WorkflowNode(
            id: "master",
            name: "Master Planner",
            type: "Master",
            position: CGPoint(x: 400, y: 100),
            status: state.status == "completed" ? "completed" : (state.status == "failed" ? "failed" : "active")
        ))
        
        // Graph nodes
        let nodeNames = state.nodes.isEmpty ? ["retrieve_context", "generate_plan", "execute_step", "verify_step", "finalize"] : state.nodes
        let spacing: CGFloat = 150
        let startX: CGFloat = 400 - CGFloat(nodeNames.count - 1) * spacing / 2
        
        for (index, nodeName) in nodeNames.enumerated() {
            let x = startX + CGFloat(index) * spacing
            let y: CGFloat = 300
            
            var status = "pending"
            if nodeName == state.currentNode {
                status = "active"
            } else if state.status == "completed" && index < nodeNames.count - 1 {
                status = "completed"
            } else if state.status == "failed" && nodeName == state.currentNode {
                status = "failed"
            }
            
            newNodes.append(WorkflowNode(
                id: nodeName,
                name: nodeName.replacingOccurrences(of: "_", with: " ").capitalized,
                type: nodeName.contains("execute") ? "Action" : (nodeName.contains("verify") ? "Verification" : "Sub"),
                position: CGPoint(x: x, y: y),
                status: status
            ))
        }
        
        nodes = newNodes
    }
}
