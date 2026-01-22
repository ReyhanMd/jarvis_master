import SwiftUI

struct TaskResultView: View {
    let taskId: String
    @State private var result: TaskStatusResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Task Results")
                    .font(.headline)
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.7) }
                Button("Refresh") { load() }
                    .disabled(isLoading)
            }

            if let error = errorMessage {
                Text(error).foregroundColor(.red).font(.caption)
            }

            if let result = result {
                Text("Status: \(result.status)")
                    .font(.subheadline)
                if let summary = result.summary {
                    Text(summary)
                        .font(.body)
                        .padding()
                        .background(Color.gray.opacity(0.1))
                        .cornerRadius(8)
                }
                if let artifacts = result.result?.artifacts {
                    VStack(alignment: .leading) {
                        Text("Artifacts").font(.subheadline)
                        ForEach(artifacts.keys.sorted(), id: \.self) { key in
                            Text("\(key): \(artifacts[key] ?? "")")
                                .font(.caption)
                        }
                    }
                }
            } else {
                Text("No result yet.")
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .onAppear { load() }
    }

    private func load() {
        Task {
            await MainActor.run {
                isLoading = true
                errorMessage = nil
            }
            do {
                let status = try await TaskService.shared.fetchStatus(taskId: taskId)
                await MainActor.run {
                    self.result = status
                    self.isLoading = false
                }
            } catch {
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                    self.isLoading = false
                }
            }
        }
    }
}
