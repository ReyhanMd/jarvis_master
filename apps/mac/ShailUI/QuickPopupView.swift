import SwiftUI

struct QuickPopupView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @State private var query: String = ""
    @State private var isListening: Bool = false
    @State private var isLoading: Bool = false
    @State private var errorMessage: String?
    @State private var backendAvailable: Bool = false
    
    var body: some View {
        VStack(spacing: 16) {
            // Header with Permission Status
            HStack {
                Text("Hello Reyhan")
                    .font(.title2)
                    .fontWeight(.bold)
                Spacer()
                
                // Permission Status
                PermissionStatusView()
                
                // Listening Indicator
                if isListening {
                    Circle()
                        .fill(Color.red)
                        .frame(width: 10, height: 10)
                        .opacity(isListening ? 1 : 0)
                        .animation(Animation.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: isListening)
                }
            }
            .padding(.horizontal, 4)
            
            // Backend Status Indicator
            if !backendAvailable {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                        .font(.caption)
                    Text("Backend unavailable")
                        .font(.caption)
                        .foregroundColor(.orange)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.orange.opacity(0.1))
                .cornerRadius(8)
            }
            
            // Error Message
            if let error = errorMessage {
                HStack {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundColor(.red)
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.red)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.red.opacity(0.1))
                .cornerRadius(8)
            }
            
            // Search Bar
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundColor(.gray)
                
                TextField("Hinted search text...", text: $query, onCommit: {
                    submitQuery()
                })
                .textFieldStyle(PlainTextFieldStyle())
                .font(.system(size: 18))
                .disabled(isLoading)
                
                if isLoading {
                    ProgressView()
                        .scaleEffect(0.7)
                        .frame(width: 20, height: 20)
                } else if !query.isEmpty {
                    Button(action: {
                        submitQuery()
                    }) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 24))
                            .foregroundColor(.blue)
                    }
                    .buttonStyle(PlainButtonStyle())
                }
                
                Button(action: {
                    isListening.toggle()
                    // TODO: Phase 7 - Connect to voice input
                }) {
                    Image(systemName: isListening ? "mic.fill" : "mic")
                        .foregroundColor(isListening ? .red : .gray)
                }
                .buttonStyle(PlainButtonStyle())
            }
            .padding()
            .background(Color.white.opacity(0.8))
            .cornerRadius(16)
            
            Text("Tip: 3-finger swipe up to preview active desktops")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding()
        .frame(width: 500)
        .background(VisualEffectBlur(material: .hudWindow, blendingMode: .behindWindow))
        .cornerRadius(20)
        .onAppear {
            checkBackendHealth()
        }
        // Gesture for 3-finger swipe
        .gesture(
            DragGesture()
                .onEnded { value in
                    if value.translation.height < -100 { // Swipe Up
                        coordinator.showBirdsEye()
                    }
                }
        )
    }
    
    private func submitQuery() {
        guard !query.isEmpty && !isLoading else { return }
        
        isLoading = true
        errorMessage = nil
        
        Task {
            do {
                let response = try await ChatService.shared.sendMessage(query)
                
                // Store response in coordinator for ChatOverlayView
                await MainActor.run {
                    isLoading = false
                    coordinator.lastChatResponse = response.text
                    coordinator.showChat()
                }
            } catch {
                await MainActor.run {
                    isLoading = false
                    errorMessage = error.localizedDescription
                }
            }
        }
    }
    
    private func checkBackendHealth() {
        Task {
            let available = await ChatService.shared.checkHealth()
            await MainActor.run {
                backendAvailable = available
            }
        }
    }
}
