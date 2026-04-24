import SwiftUI
import AppKit

// MARK: - Main chat overlay

struct ChatOverlayView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    @StateObject private var wsClient = BackendWebSocketClient()

    @State private var inputText: String = ""
    @State private var isLoading: Bool   = false

    var body: some View {
        VStack(spacing: 0) {
            chatHeader
            messageList
            inputBar
        }
        .frame(maxWidth: .infinity)
        .background(ShailTheme.glassBackground())
        .cornerRadius(ShailTheme.cornerRadius)
        .overlay(ShailTheme.glassStroke())
        .onAppear {
            wsClient.connect()
            seedInitialMessage()
            loadHistory()
        }
    }

    // MARK: - Header

    private var chatHeader: some View {
        HStack(spacing: 12) {
            Button { coordinator.showPopup() } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white.opacity(0.55))
            }
            .buttonStyle(.plain)

            HStack(spacing: 5) {
                Image(systemName: "bolt.fill")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(ShailTheme.primaryGradient)
                Text("SHAIL")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .foregroundColor(.white.opacity(0.9))
            }

            Spacer()

            Button { coordinator.showBirdsEye() } label: {
                Label("Workflow", systemImage: "arrow.triangle.branch")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundColor(.white.opacity(0.45))
            }
            .buttonStyle(.plain)

            Button { coordinator.collapseToLauncher?() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(.white.opacity(0.35))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color.white.opacity(0.05))
    }

    // MARK: - Messages

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    ForEach(coordinator.messages) { msg in
                        MessageBubble(message: msg).id(msg.id)
                    }
                    if let taskId = coordinator.activeTaskId {
                        TaskProgressCard(taskId: taskId)
                            .padding(.horizontal, 14)
                            .id("task-progress")
                    }
                    if isLoading { ThinkingBubble().id("thinking") }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
            }
            .onChange(of: coordinator.messages.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo("bottom", anchor: .bottom) }
            }
            .onChange(of: coordinator.activeTaskId) { _, _ in
                withAnimation { proxy.scrollTo("task-progress", anchor: .bottom) }
            }
            .onChange(of: isLoading) { _, _ in
                withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
            }
        }
        .frame(minHeight: 220, maxHeight: .infinity)
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 10) {
            TextField(
                "",
                text: $inputText,
                prompt: Text("Reply to SHAIL…").foregroundColor(.white.opacity(0.3))
            )
            .textFieldStyle(.plain)
            .font(.system(size: 15, design: .rounded))
            .foregroundColor(.white)
            .onSubmit { sendMessage() }
            .disabled(isLoading)

            if isLoading {
                ProgressView().scaleEffect(0.65).tint(ShailTheme.primaryBlue)
            } else {
                Button { sendMessage() } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 24))
                        .foregroundStyle(
                            inputText.isEmpty
                                ? AnyShapeStyle(Color.white.opacity(0.2))
                                : AnyShapeStyle(ShailTheme.primaryGradient)
                        )
                }
                .buttonStyle(.plain)
                .disabled(inputText.isEmpty)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .background(Color.white.opacity(0.07))
        .overlay(Rectangle().frame(height: 1).foregroundColor(.white.opacity(0.08)), alignment: .top)
    }

    // MARK: - Logic

    private func seedInitialMessage() {
        guard coordinator.messages.isEmpty, let initial = coordinator.lastChatResponse else { return }
        coordinator.messages.append(ChatMessage(text: initial, role: .assistant))
    }

    private func loadHistory() {
        guard coordinator.messages.isEmpty else { return }
        Task {
            guard let history = try? await ChatHistoryService.shared.fetchHistory(),
                  !history.isEmpty else { return }
            await MainActor.run {
                if coordinator.messages.isEmpty {
                    coordinator.messages = history
                }
            }
        }
    }

    private func sendMessage() {
        guard !inputText.isEmpty else { return }
        let text  = inputText
        inputText = ""
        isLoading = true
        coordinator.messages.append(ChatMessage(text: text, role: .user))

        Task {
            do {
                let response = try await ChatService.shared.sendMessage(text)
                await MainActor.run {
                    isLoading = false
                    coordinator.messages.append(ChatMessage(text: response.text, role: .assistant))
                    coordinator.lastChatResponse = response.text
                }
            } catch {
                await MainActor.run {
                    isLoading = false
                    coordinator.messages.append(
                        ChatMessage(text: "⚠️ \(error.localizedDescription)", role: .assistant)
                    )
                }
            }
        }
    }
}

// MARK: - Message bubble

struct MessageBubble: View {
    let message: ChatMessage
    @State private var isHovered = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if message.role == .user      { Spacer(minLength: 48) }
            if message.role == .assistant { shailAvatar }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 3) {
                ZStack(alignment: message.role == .user ? .topTrailing : .topLeading) {
                    Text(message.text)
                        .font(ShailTheme.bodyFont)
                        .foregroundColor(.white)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 9)
                        .background(bubbleBackground)
                        .fixedSize(horizontal: false, vertical: true)

                    if isHovered {
                        Button {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(message.text, forType: .string)
                        } label: {
                            Image(systemName: "doc.on.doc")
                                .font(.system(size: 10))
                                .foregroundColor(.white.opacity(0.8))
                                .padding(5)
                                .background(Circle().fill(Color.black.opacity(0.45)))
                        }
                        .buttonStyle(.plain)
                        .offset(
                            x: message.role == .user ? -6 : 6,
                            y: -6
                        )
                        .transition(.opacity)
                    }
                }

                Text(message.timestamp.formatted(date: .omitted, time: .shortened))
                    .font(.system(size: 9, design: .rounded))
                    .foregroundColor(.white.opacity(0.25))
                    .padding(.horizontal, 4)
            }

            if message.role == .assistant { Spacer(minLength: 48) }
        }
        .onHover { hovering in
            withAnimation(.easeInOut(duration: 0.15)) { isHovered = hovering }
        }
    }

    private var shailAvatar: some View {
        ZStack {
            Circle().fill(ShailTheme.primaryGradient).frame(width: 26, height: 26)
            Image(systemName: "bolt.fill").font(.system(size: 11, weight: .bold)).foregroundColor(.white)
        }
    }

    @ViewBuilder
    private var bubbleBackground: some View {
        if message.role == .user {
            RoundedRectangle(cornerRadius: 16).fill(ShailTheme.primaryBlue)
        } else {
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.white.opacity(0.11))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.14), lineWidth: 1))
        }
    }
}

// MARK: - Task Progress Card

struct TaskProgressCard: View {
    let taskId: String
    @State private var status: String = "queued"
    @State private var summary: String?
    @State private var isDone = false
    @State private var pollingTimer: Timer?

    var body: some View {
        if !isDone {
            HStack(spacing: 10) {
                statusIcon
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 2) {
                    Text(statusLabel)
                        .font(ShailTheme.captionFont)
                        .foregroundColor(.white.opacity(0.85))
                    if let s = summary {
                        Text(s)
                            .font(.system(size: 11, design: .rounded))
                            .foregroundColor(.white.opacity(0.5))
                            .lineLimit(2)
                    }
                }

                Spacer()

                Text(taskId.prefix(8))
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundColor(.white.opacity(0.2))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.white.opacity(0.07))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(statusBorderColor, lineWidth: 1)
                    )
            )
            .onAppear { startPolling() }
            .onDisappear { pollingTimer?.invalidate() }
        }
    }

    private var statusLabel: String {
        switch status {
        case "queued":              return "Task queued…"
        case "planning":            return "Planning…"
        case "executing", "running": return "Executing…"
        case "completed":           return "Done"
        case "failed":              return "Failed"
        default:                    return status.capitalized + "…"
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch status {
        case "completed":
            Image(systemName: "checkmark.circle.fill")
                .foregroundColor(.green)
                .font(.system(size: 14))
        case "failed":
            Image(systemName: "xmark.circle.fill")
                .foregroundColor(.red)
                .font(.system(size: 14))
        default:
            ProgressView()
                .scaleEffect(0.6)
                .tint(ShailTheme.primaryBlue)
        }
    }

    private var statusBorderColor: Color {
        switch status {
        case "completed": return Color.green.opacity(0.35)
        case "failed":    return Color.red.opacity(0.35)
        default:          return Color.white.opacity(0.12)
        }
    }

    private func startPolling() {
        poll()
        pollingTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in poll() }
    }

    private func poll() {
        Task {
            guard let result = try? await TaskService.shared.fetchStatus(taskId: taskId) else { return }
            await MainActor.run {
                withAnimation(.easeInOut(duration: 0.2)) {
                    status  = result.status
                    summary = result.summary ?? result.result?.summary
                }
                if ["completed", "failed"].contains(result.status) {
                    pollingTimer?.invalidate()
                    DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                        withAnimation { isDone = true }
                    }
                }
            }
        }
    }
}

// MARK: - Thinking indicator

struct ThinkingBubble: View {
    @State private var scales: [CGFloat] = [0.5, 0.5, 0.5]

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ZStack {
                Circle().fill(ShailTheme.primaryGradient).frame(width: 26, height: 26)
                Image(systemName: "bolt.fill").font(.system(size: 11, weight: .bold)).foregroundColor(.white)
            }
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(Color.white.opacity(0.55)).frame(width: 7, height: 7).scaleEffect(scales[i])
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 16).fill(Color.white.opacity(0.10)))
            Spacer(minLength: 48)
        }
        .onAppear {
            for i in 0..<3 {
                withAnimation(.easeInOut(duration: 0.45).repeatForever(autoreverses: true).delay(Double(i) * 0.15)) {
                    scales[i] = 1.0
                }
            }
        }
    }
}
