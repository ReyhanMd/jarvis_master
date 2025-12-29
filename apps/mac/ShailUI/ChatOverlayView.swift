import SwiftUI

struct ChatOverlayView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @State private var messageText: String = ""
    @State private var isLoading: Bool = false
    
    var body: some View {
        VStack {
            // Chat Bubble (Orange Box)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    // Show last response if available
                    if let response = coordinator.lastChatResponse {
                        HStack(alignment: .top) {
                            Text("SHAIL")
                                .font(.caption)
                                .fontWeight(.bold)
                                .foregroundColor(.secondary)
                                .frame(width: 50)
                            
                            Text(response)
                                .padding(10)
                                .background(Color.orange.opacity(0.15))
                                .cornerRadius(8)
                        }
                    } else {
                        Text("No response yet")
                            .foregroundColor(.secondary)
                            .padding()
                    }
                }
                .padding()
            }
            .frame(maxHeight: 300)
            .background(Color.white.opacity(0.9))
            .cornerRadius(12)
            .shadow(radius: 5)
            
            // Input Area
            HStack {
                TextField("Reply...", text: $messageText)
                    .textFieldStyle(RoundedBorderTextFieldStyle())
                    .disabled(isLoading)
                
                if isLoading {
                    ProgressView()
                        .scaleEffect(0.7)
                } else {
                Button("Send") {
                        sendMessage()
                    }
                    .disabled(messageText.isEmpty)
                }
            }
            .padding(.top, 8)
            
            // Navigation buttons
            HStack {
                Button("Back to Popup") {
                    coordinator.showPopup()
                }
                .font(.caption)
                
                Spacer()
                
            Button("View Workflow (Bird's Eye)") {
                coordinator.showBirdsEye()
            }
            .font(.caption)
            }
            .padding(.top)
        }
        .padding()
        .frame(width: 450)
        .background(VisualEffectBlur(material: .popover, blendingMode: .behindWindow))
        .cornerRadius(16)
    }
    
    private func sendMessage() {
        guard !messageText.isEmpty && !isLoading else { return }
        
        let query = messageText
        messageText = ""
        isLoading = true
        
        Task {
            do {
                let response = try await ChatService.shared.sendMessage(query)
                
                await MainActor.run {
                    isLoading = false
                    coordinator.lastChatResponse = response.text
                }
            } catch {
                await MainActor.run {
                    isLoading = false
                    messageText = query // Restore message on error
                }
            }
        }
    }
}
