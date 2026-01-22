import SwiftUI

struct QuickPopupView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @StateObject private var wsClient = BackendWebSocketClient()
    @StateObject private var desktopManager = DesktopManager()
    @State private var query: String = ""
    @State private var isListening: Bool = false
    @State private var isLoading: Bool = false
    @State private var errorMessage: String?
    @State private var backendAvailable: Bool = false
    @State private var nativeHealth: NativeHealthStatus?
    @State private var pendingPermission: PermissionRequest?
    @State private var showSettings: Bool = false
    
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

            if let health = nativeHealth {
                let captureOk = health.capture == "connected"
                let accessibilityOk = health.accessibility == "connected"
                let groundingOk = captureOk && accessibilityOk
                HStack(spacing: 6) {
                    Image(systemName: groundingOk ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .foregroundColor(groundingOk ? .green : .orange)
                        .font(.caption)
                    Text(groundingOk ? "Grounding Active" : "Grounding Inactive")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("Capture: \(health.capture)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Text("AX: \(health.accessibility)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.gray.opacity(0.1))
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

                Button(action: {
                    showSettings = true
                }) {
                    Image(systemName: "gearshape.fill")
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
            checkNativeHealth()
            checkPermissionsAwaiting()
            wsClient.connect()
        }
        .onChange(of: wsClient.permissionRequest) { newRequest in
            if let request = newRequest {
                pendingPermission = request
            }
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
        .sheet(item: $pendingPermission) { request in
            PermissionRequestView(
                request: request,
                onApprove: {
                    Task {
                        try? await PermissionService.shared.approve(taskId: request.taskId)
                        pendingPermission = nil
                    }
                },
                onDeny: {
                    Task {
                        try? await PermissionService.shared.deny(taskId: request.taskId)
                        pendingPermission = nil
                    }
                }
            )
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
    }
    
    private func submitQuery() {
        guard !query.isEmpty && !isLoading else { return }
        
        isLoading = true
        errorMessage = nil
        
        Task {
            do {
                // Submit as task to include desktop_id for testing
                let desktopId = desktopManager.activeDesktop
                let taskResponse = try await TaskService.shared.submitTask(
                    text: query,
                    mode: "auto",
                    desktopId: desktopId
                )
                
                // Also get quick chat response for immediate feedback
                let response = try await ChatService.shared.sendMessage(query)
                
                // Store response in coordinator for ChatOverlayView
                await MainActor.run {
                    isLoading = false
                    coordinator.lastChatResponse = response.text
                    coordinator.activeTaskId = taskResponse.task_id
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
    
    /// Submit a task (for complex operations that need planning)
    private func submitTask(_ text: String) {
        Task {
            do {
                // Get current desktop ID
                let desktopId = desktopManager.activeDesktop
                
                // Submit task with desktop context
                let response = try await TaskService.shared.submitTask(
                    text: text,
                    mode: "auto",
                    desktopId: desktopId
                )
                
                await MainActor.run {
                    coordinator.activeTaskId = response.task_id
                    // Show task result view or notification
                }
            } catch {
                await MainActor.run {
                    errorMessage = "Failed to submit task: \(error.localizedDescription)"
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

    private func checkNativeHealth() {
        Task {
            guard let url = URL(string: "http://localhost:8000/health/native") else { return }
            do {
                let (data, response) = try await URLSession.shared.data(from: url)
                guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                    return
                }
                let decoded = try JSONDecoder().decode(NativeHealthStatus.self, from: data)
                await MainActor.run {
                    nativeHealth = decoded
                }
            } catch {
                // ignore
            }
        }
    }

    private func checkPermissionsAwaiting() {
        Task {
            do {
                let list = try await PermissionService.shared.fetchAwaitingApproval()
                await MainActor.run {
                    pendingPermission = list.first
                }
            } catch {
                // ignore
            }
        }
    }
}
