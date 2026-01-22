import SwiftUI

struct ChatHistoryView: View {
    @State private var messages: [ChatMessage] = []
    @State private var searchText: String = ""
    @State private var isLoading = false
    @State private var errorMessage: String?
    
    var filteredMessages: [ChatMessage] {
        guard !searchText.isEmpty else { return messages }
        return messages.filter { $0.text.localizedCaseInsensitiveContains(searchText) }
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Chat History")
                    .font(.headline)
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.7) }
            }
            
            HStack {
                TextField("Search history...", text: $searchText)
                    .textFieldStyle(RoundedBorderTextFieldStyle())
                Button("Refresh") { loadHistory() }
                    .disabled(isLoading)
            }
            
            if let error = errorMessage {
                Text(error)
                    .foregroundColor(.red)
                    .font(.caption)
            }
            
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(filteredMessages) { msg in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(msg.role == .user ? "You" : "Shail")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                Spacer()
                                Text(msg.timestamp, style: .time)
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                            Text(msg.text)
                                .font(.body)
                                .padding(8)
                                .background(msg.role == .user ? Color.blue.opacity(0.1) : Color.orange.opacity(0.1))
                                .cornerRadius(8)
                        }
                        .padding(.vertical, 4)
                        Divider()
                    }
                }
            }
        }
        .padding()
        .onAppear { loadHistory() }
    }
    
    private func loadHistory() {
        Task {
            await MainActor.run {
                isLoading = true
                errorMessage = nil
            }
            do {
                let history = try await ChatHistoryService.shared.fetchHistory()
                await MainActor.run {
                    self.messages = history
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
