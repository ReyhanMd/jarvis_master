import SwiftUI

struct DetailView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @StateObject private var wsClient = BackendWebSocketClient()
    
    // Simulating "Desktops"
    let desktopApps = ["SolidWorks", "MATLAB", "Excel", "Chrome"]
    
    var body: some View {
        VStack(spacing: 0) {
            topTaskbar
            mainContent
        }
        .frame(minWidth: 800, minHeight: 600)
        .onAppear {
            wsClient.connect()
        }
    }
    
    private var topTaskbar: some View {
        HStack {
            Button(action: { coordinator.showBirdsEye() }) {
                HStack {
                    Image(systemName: "arrow.left")
                    Text("Back to Graph")
                }
                .foregroundColor(.white)
            }
            .padding(.leading)
            
            Spacer()
            
            if let nodeId = coordinator.selectedNodeId {
                Text(nodeId.replacingOccurrences(of: "_", with: " ").capitalized)
                    .font(.headline)
                    .foregroundColor(.white)
            } else if let desktop = coordinator.activeDesktop {
                Text(desktop)
                    .font(.headline)
                    .foregroundColor(.white)
            }
            
            Spacer()
            
            Button(action: { print("Summon Gemini 3 Pro") }) {
                Image(systemName: "brain.head.profile")
                    .foregroundColor(.white)
            }
            .padding(.trailing)
        }
        .padding()
        .background(Color.blue)
    }
    
    @ViewBuilder
    private var mainContent: some View {
        if let nodeId = coordinator.selectedNodeId {
            nodeDetailView(nodeId: nodeId)
        } else {
            desktopView
        }
    }
    
    private func nodeDetailView(nodeId: String) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                nodeHeader(nodeId: nodeId)
                Divider()
                if let state = wsClient.currentState {
                    nodeStatusView(nodeId: nodeId, state: state)
                    if nodeId == "execute_step" || nodeId.contains("execute") {
                        executionStepsView(state: state)
                    }
                    nodeInfoView(state: state)
                    taskResultsView
                    if let error = state.error {
                        errorView(error: error)
                    }
                } else {
                    Text("No state data available")
                        .foregroundColor(.secondary)
                        .padding()
                }
            }
            .padding(.vertical)
        }
        .background(Color.white)
    }
    
    private func nodeHeader(nodeId: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Node Details")
                .font(.title)
                .fontWeight(.bold)
            
            Text(nodeId.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.title2)
                .foregroundColor(.secondary)
        }
        .padding()
    }
    
    private func nodeStatusView(nodeId: String, state: GraphState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Status")
                .font(.headline)
            
            HStack {
                Circle()
                    .fill(statusColor(state.status))
                    .frame(width: 12, height: 12)
                Text(state.status.capitalized)
                    .font(.body)
            }
            
            if nodeId == state.currentNode {
                Label("Currently Active", systemImage: "circle.fill")
                    .font(.caption)
                    .foregroundColor(.orange)
            }
        }
        .padding()
        .background(Color.gray.opacity(0.1))
        .cornerRadius(8)
        .padding(.horizontal)
    }
    
    private func executionStepsView(state: GraphState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Execution Steps")
                .font(.headline)
            
            ForEach(Array(state.planSteps.enumerated()), id: \.element.stepId) { index, step in
                stepRow(index: index, step: step)
            }
        }
        .padding()
    }
    
    private func stepRow(index: Int, step: PlanStep) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Circle()
                    .fill(stepColor(step))
                    .frame(width: 8, height: 8)
                Text("Step \(index + 1)")
                    .font(.subheadline)
                    .fontWeight(.semibold)
                
                Spacer()
                
                if step.executed {
                    Image(systemName: step.success == true ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundColor(step.success == true ? .green : .red)
                }
            }
            
            Text(step.description)
                .font(.body)
                .padding(.leading, 20)
            
            if let error = step.error {
                Text("Error: \(error)")
                    .font(.caption)
                    .foregroundColor(.red)
                    .padding(.leading, 20)
            }
            
            if step.executed {
                Text("Executed")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.leading, 20)
            }
        }
        .padding()
        .background(Color.white)
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(step.executed ? (step.success == true ? Color.green : Color.red) : Color.gray.opacity(0.3), lineWidth: 1)
        )
    }
    
    private func nodeInfoView(state: GraphState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Node Information")
                .font(.headline)
            
            InfoRow(label: "Node ID", value: coordinator.selectedNodeId ?? "N/A")
            InfoRow(label: "Current Step", value: "\(state.currentStepIndex + 1) / \(state.stepCount)")
            InfoRow(label: "Task ID", value: state.taskId ?? "N/A")
            if let planId = state.planId {
                InfoRow(label: "Plan ID", value: planId)
            }
        }
        .padding()
        .background(Color.gray.opacity(0.1))
        .cornerRadius(8)
        .padding(.horizontal)
    }
    
    private var taskResultsView: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Task Results")
                .font(.headline)
            TextField("Enter task ID", text: Binding(
                get: { coordinator.activeTaskId ?? "" },
                set: { coordinator.activeTaskId = $0.isEmpty ? nil : $0 }
            ))
            .textFieldStyle(RoundedBorderTextFieldStyle())
            if let taskId = coordinator.activeTaskId, !taskId.isEmpty {
                TaskResultView(taskId: taskId)
            }
        }
        .padding()
        .background(Color.gray.opacity(0.05))
        .cornerRadius(8)
        .padding(.horizontal)
    }
    
    private func errorView(error: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Error")
                .font(.headline)
                .foregroundColor(.red)
            
            Text(error)
                .font(.body)
                .foregroundColor(.red)
        }
        .padding()
        .background(Color.red.opacity(0.1))
        .cornerRadius(8)
        .padding(.horizontal)
    }
    
    private var desktopView: some View {
        ZStack {
            Color.white
            
            VStack {
                Spacer()
                Text("Active Desktop: \(coordinator.activeDesktop ?? "None")")
                    .font(.largeTitle)
                    .foregroundColor(.gray.opacity(0.5))
                Spacer()
            }
        }
    }
    
    func statusColor(_ status: String) -> Color {
        switch status {
        case "active": return .orange
        case "completed": return .green
        case "failed": return .red
        default: return .gray
        }
    }
    
    func stepColor(_ step: PlanStep) -> Color {
        if let success = step.success {
            return success ? .green : .red
        }
        return step.executed ? .blue : .gray
    }
}

struct InfoRow: View {
    let label: String
    let value: String
    
    var body: some View {
        HStack {
            Text(label + ":")
                .font(.subheadline)
                .foregroundColor(.secondary)
            Spacer()
            Text(value)
                .font(.subheadline)
                .fontWeight(.medium)
        }
    }
}
