import Foundation
import Combine

/// WebSocket client for /ws/brain — receives real-time LangGraph state updates and permission requests.
class BackendWebSocketClient: ObservableObject {
    @Published var isConnected: Bool = false
    @Published var currentState: GraphState?
    @Published var errorMessage: String?
    @Published var permissionRequest: PermissionRequest?

    private var webSocketTask: URLSessionWebSocketTask?
    private let url: URL
    private var reconnectTimer: Timer?
    private var shouldReconnect: Bool = true
    private var connectionStateObserver: NSKeyValueObservation?
    private var reconnectAttempts: Int = 0
    private var pingTimer: Timer?

    init(url: URL = URL(string: "ws://localhost:8000/ws/brain")!) {
        self.url = url
    }

    // MARK: - Connection

    func connect() {
        guard !isConnected else { return }

        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)

        setupConnectionStateObserver()
        receiveMessage()
        webSocketTask?.resume()

        errorMessage = nil
    }

    func disconnect() {
        shouldReconnect = false
        connectionStateObserver?.invalidate()
        connectionStateObserver = nil
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        reconnectAttempts = 0
    }

    // MARK: - Private

    private func setupConnectionStateObserver() {
        guard let task = webSocketTask else { return }

        connectionStateObserver = task.observe(\.state, options: [.new, .initial]) { [weak self] task, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch task.state {
                case .running:
                    if !self.isConnected {
                        self.isConnected = true
                        self.errorMessage = nil
                        self.reconnectAttempts = 0
                        self.sendPing()
                    }
                case .suspended, .canceling, .completed:
                    self.isConnected = false
                @unknown default:
                    self.isConnected = false
                }
            }
        }
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }

            switch result {
            case .success(let message):
                if !self.isConnected {
                    DispatchQueue.main.async {
                        self.isConnected = true
                        self.errorMessage = nil
                        self.reconnectAttempts = 0
                        self.sendPing()
                    }
                }

                switch message {
                case .string(let text):  self.handleMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) { self.handleMessage(text) }
                @unknown default: break
                }

                self.receiveMessage()

            case .failure(let error):
                let nsError = error as NSError
                DispatchQueue.main.async {
                    self.isConnected = false
                    self.errorMessage = "WebSocket error: \(nsError.localizedDescription)"
                }
                if self.shouldReconnect { self.scheduleReconnect() }
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

        switch json["type"] as? String {
        case "state_update":
            if let stateData = json["state"] as? [String: Any] {
                DispatchQueue.main.async { self.currentState = GraphState(from: stateData) }
            }

        case "state_history":
            if let states = json["states"] as? [[String: Any]], let last = states.last {
                DispatchQueue.main.async { self.currentState = GraphState(from: last) }
            }

        case "event":
            let eventType = json["event_type"] as? String
            if eventType == "permission_requested", let eventData = json["data"] as? [String: Any] {
                DispatchQueue.main.async { self.handlePermissionRequest(eventData) }
            }

        case "pong":
            break // keepalive confirmed

        default:
            break
        }
    }

    private func handlePermissionRequest(_ data: [String: Any]) {
        guard let taskId = data["task_id"] as? String,
              let toolName = data["tool_name"] as? String else { return }

        let toolArgs = (data["tool_args"] as? [String: Any]) ?? [:]
        let rationale = data["rationale"] as? String ?? ""

        let toolArgsString: String
        if let encoded = try? JSONSerialization.data(withJSONObject: toolArgs),
           let str = String(data: encoded, encoding: .utf8) {
            toolArgsString = str
        } else {
            toolArgsString = "{}"
        }

        permissionRequest = PermissionRequest(
            taskId: taskId,
            toolName: toolName,
            toolArgs: toolArgsString,
            rationale: rationale
        )
    }

    private func sendPing() {
        guard isConnected, let task = webSocketTask else { return }

        let ping = ["type": "ping"]
        guard let data = try? JSONSerialization.data(withJSONObject: ping),
              let text = String(data: data, encoding: .utf8) else { return }

        task.send(.string(text)) { [weak self] error in
            if error != nil {
                DispatchQueue.main.async { self?.isConnected = false }
            }
        }

        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: false) { [weak self] _ in
            guard let self = self, self.isConnected else { return }
            self.sendPing()
        }
    }

    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        reconnectAttempts += 1
        let delay = min(5.0 * pow(2.0, Double(reconnectAttempts - 1)), 60.0)
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self, self.shouldReconnect else { return }
            self.connect()
        }
    }

    deinit { disconnect() }
}

// MARK: - Models

struct GraphEdge {
    let from: String
    let to: String
    let condition: String?

    init(from dict: [String: Any]) {
        from      = dict["from"]      as? String ?? ""
        to        = dict["to"]        as? String ?? ""
        condition = dict["condition"] as? String
    }
}

struct GraphState {
    let taskDescription: String
    let currentStep: Int
    let status: String
    let error: String?
    let planSteps: [PlanStep]
    let currentNode: String
    let nodes: [String]
    let edges: [GraphEdge]
    let planId: String?
    let taskId: String?
    let stepCount: Int
    let currentStepIndex: Int

    init(from dict: [String: Any]) {
        taskDescription  = dict["task_description"]   as? String ?? ""
        currentStep      = dict["current_step"]       as? Int    ?? 0
        status           = dict["status"]             as? String ?? "unknown"
        error            = dict["error"]              as? String
        currentNode      = dict["current_node"]       as? String ?? "unknown"
        nodes            = dict["nodes"]              as? [String] ?? []
        planId           = dict["plan_id"]            as? String
        taskId           = dict["task_id"]            as? String
        stepCount        = dict["step_count"]         as? Int    ?? 0
        currentStepIndex = dict["current_step_index"] as? Int    ?? 0

        edges = (dict["edges"] as? [[String: Any]] ?? []).map { GraphEdge(from: $0) }

        planSteps = (dict["plan_steps"] as? [[String: Any]] ?? []).map { PlanStep(from: $0) }
    }
}

struct PlanStep {
    let stepId: String
    let description: String
    let stepType: String
    let executed: Bool
    let success: Bool?
    let error: String?

    init(from dict: [String: Any]) {
        stepId      = dict["step_id"]     as? String ?? ""
        description = dict["description"] as? String ?? ""
        stepType    = dict["step_type"]   as? String ?? "action"
        executed    = dict["executed"]    as? Bool   ?? false
        success     = dict["success"]     as? Bool
        error       = dict["error"]       as? String
    }
}
