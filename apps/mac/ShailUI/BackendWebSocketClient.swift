import Foundation
import Combine

/// WebSocket client for connecting to backend /ws/brain endpoint
/// Receives real-time LangGraph state updates
class BackendWebSocketClient: ObservableObject {
    @Published var isConnected: Bool = false
    @Published var currentState: GraphState?
    @Published var errorMessage: String?
    
    private var webSocketTask: URLSessionWebSocketTask?
    private let url: URL
    private var reconnectTimer: Timer?
    private var shouldReconnect: Bool = true
    
    init(url: URL = URL(string: "ws://localhost:8000/ws/brain")!) {
        self.url = url
    }
    
    /// Connect to WebSocket server
    func connect() {
        guard !isConnected else { return }
        
        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        
        receiveMessage()
        sendPing()
        
        isConnected = true
        errorMessage = nil
        
        print("🔌 Connected to backend WebSocket")
    }
    
    /// Disconnect from WebSocket server
    func disconnect() {
        shouldReconnect = false
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        
        print("🔌 Disconnected from backend WebSocket")
    }
    
    /// Receive messages from server
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    self.handleMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) {
                        self.handleMessage(text)
                    }
                @unknown default:
                    break
                }
                
                // Continue receiving
                self.receiveMessage()
                
            case .failure(let error):
                print("❌ WebSocket receive error: \(error)")
                self.isConnected = false
                self.errorMessage = error.localizedDescription
                
                // Attempt reconnection
                if self.shouldReconnect {
                    self.scheduleReconnect()
                }
            }
        }
    }
    
    /// Handle incoming message
    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        
        let messageType = json["type"] as? String
        
        switch messageType {
        case "state_update":
            if let stateData = json["state"] as? [String: Any] {
                DispatchQueue.main.async {
                    self.currentState = GraphState(from: stateData)
                }
            }
            
        case "state_history":
            if let states = json["states"] as? [[String: Any]], let lastState = states.last {
                DispatchQueue.main.async {
                    self.currentState = GraphState(from: lastState)
                }
            }
            
        case "event":
            let eventType = json["event_type"] as? String
            print("📨 Event: \(eventType ?? "unknown")")
            
        case "pong":
            // Ping response
            break
            
        default:
            print("📨 Unknown message type: \(messageType ?? "nil")")
        }
    }
    
    /// Send ping to keep connection alive
    private func sendPing() {
        let ping = ["type": "ping"]
        guard let data = try? JSONSerialization.data(withJSONObject: ping),
              let text = String(data: data, encoding: .utf8) else {
            return
        }
        
        let message = URLSessionWebSocketTask.Message.string(text)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("❌ Ping send error: \(error)")
            }
        }
        
        // Schedule next ping in 30 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            self?.sendPing()
        }
    }
    
    /// Schedule reconnection attempt
    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { [weak self] _ in
            self?.connect()
        }
    }
    
    deinit {
        disconnect()
    }
}

/// Graph edge model
struct GraphEdge {
    let from: String
    let to: String
    let condition: String?
    
    init(from dict: [String: Any]) {
        from = dict["from"] as? String ?? ""
        to = dict["to"] as? String ?? ""
        condition = dict["condition"] as? String
    }
}

/// Graph state model
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
        taskDescription = dict["task_description"] as? String ?? ""
        currentStep = dict["current_step"] as? Int ?? 0
        status = dict["status"] as? String ?? "unknown"
        error = dict["error"] as? String
        currentNode = dict["current_node"] as? String ?? "unknown"
        nodes = dict["nodes"] as? [String] ?? []
        planId = dict["plan_id"] as? String
        taskId = dict["task_id"] as? String
        stepCount = dict["step_count"] as? Int ?? 0
        currentStepIndex = dict["current_step_index"] as? Int ?? 0
        
        // Parse edges
        if let edgesData = dict["edges"] as? [[String: Any]] {
            edges = edgesData.map { GraphEdge(from: $0) }
        } else {
            edges = []
        }
        
        // Parse plan steps
        if let stepsData = dict["plan_steps"] as? [[String: Any]] {
            planSteps = stepsData.map { PlanStep(from: $0) }
        } else {
            planSteps = []
        }
    }
}

/// Plan step model
struct PlanStep {
    let stepId: String
    let description: String
    let stepType: String
    let executed: Bool
    let success: Bool?
    let error: String?
    
    init(from dict: [String: Any]) {
        stepId = dict["step_id"] as? String ?? ""
        description = dict["description"] as? String ?? ""
        stepType = dict["step_type"] as? String ?? "action"
        executed = dict["executed"] as? Bool ?? false
        success = dict["success"] as? Bool
        error = dict["error"] as? String
    }
}

