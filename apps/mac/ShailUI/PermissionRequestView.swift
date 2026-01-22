import SwiftUI

struct PermissionRequest: Identifiable, Codable, Equatable {
    let id = UUID()
    let taskId: String
    let toolName: String
    let toolArgs: String
    let rationale: String
    
    static func == (lhs: PermissionRequest, rhs: PermissionRequest) -> Bool {
        return lhs.taskId == rhs.taskId && lhs.toolName == rhs.toolName
    }
}

struct PermissionRequestView: View {
    let request: PermissionRequest
    var onApprove: () -> Void
    var onDeny: () -> Void
    @State private var remember: Bool = false
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Permission Required")
                    .font(.headline)
                Spacer()
            }
            Text("Task: \(request.taskId)")
                .font(.subheadline)
            Text("Action: \(request.toolName)")
                .font(.body)
            Text("Details:")
                .font(.subheadline)
            ScrollView {
                Text(request.toolArgs)
                    .font(.caption)
                    .padding()
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(8)
            }
            .frame(height: 120)
            Text("Reason: \(request.rationale)")
                .font(.body)
            
            Toggle("Remember this permission", isOn: $remember)
                .font(.caption)
            
            HStack {
                Button("Deny") { onDeny() }
                    .buttonStyle(.bordered)
                Spacer()
                Button("Approve") { onApprove() }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .frame(minWidth: 380)
    }
}
