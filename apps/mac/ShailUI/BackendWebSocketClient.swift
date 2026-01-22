import Foundation
import Combine

/// WebSocket client for connecting to backend /ws/brain endpoint
/// Receives real-time LangGraph state updates and permission requests
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
    
    /// Get log file path, ensuring directory exists
    private func getLogPath() -> String {
        let logDir = "/Users/reyhan/jarvis_master/.cursor"
        let fileManager = FileManager.default
        if !fileManager.fileExists(atPath: logDir) {
            try? fileManager.createDirectory(atPath: logDir, withIntermediateDirectories: true, attributes: nil)
        }
        return "\(logDir)/debug.log"
    }
    
    /// Connect to WebSocket server
    func connect() {
        guard !isConnected else { return }
        
        // #region agent log
        let logData: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "A", "location": "BackendWebSocketClient.swift:connect", "message": "Attempting WebSocket connection", "data": ["url": url.absoluteString], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
        print("🔍 [DEBUG] Attempting WebSocket connection to \(url.absoluteString)")
        // Write log using simple file append
        if let jsonData = try? JSONSerialization.data(withJSONObject: logData), let jsonString = String(data: jsonData, encoding: .utf8) {
            let logPath = getLogPath()
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write((jsonString + "\n").data(using: .utf8)!)
                fileHandle.closeFile()
                print("🔍 [DEBUG] Log written to \(logPath)")
            } else {
                // File doesn't exist, create it
                do {
                    try jsonString.write(toFile: logPath, atomically: true, encoding: .utf8)
                    print("🔍 [DEBUG] Log file created at \(logPath)")
                } catch {
                    print("🔍 [DEBUG] Failed to write log: \(error)")
                }
            }
        } else {
            print("🔍 [DEBUG] Failed to serialize log data")
        }
        // #endregion
        
        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)
        
        // Set up connection state observer BEFORE resuming
        setupConnectionStateObserver()
        
        // Start receiving messages BEFORE resuming (to catch handshake completion)
        receiveMessage()
        
        // Resume the task (this starts the handshake)
        webSocketTask?.resume()
        
        // Clear error message
        errorMessage = nil
        
        // DO NOT set isConnected = true here - wait for actual connection confirmation
        print("🔄 WebSocket handshake in progress...")
    }
    
    /// Disconnect from WebSocket server
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
        
        print("🔌 Disconnected from backend WebSocket")
    }
    
    /// Setup connection state observer using KVO
    private func setupConnectionStateObserver() {
        guard let task = webSocketTask else { return }
        
        connectionStateObserver = task.observe(\.state, options: [.new, .initial]) { [weak self] task, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                
                switch task.state {
                case .running:
                    // Task is running - connection is active
                    // Set connected immediately when RUNNING (connection established)
                    if !self.isConnected {
                        self.isConnected = true
                        self.errorMessage = nil
                        self.reconnectAttempts = 0
                        print("✅ WebSocket connected (RUNNING state)")
                        // Start ping keepalive now that we're connected
                        self.sendPing()
                    }
                    print("🔄 WebSocket state: RUNNING")
                    
                case .suspended:
                    print("⏸️ WebSocket state: SUSPENDED")
                    self.isConnected = false
                    
                case .canceling:
                    print("⚠️ WebSocket state: CANCELING")
                    self.isConnected = false
                    
                case .completed:
                    print("❌ WebSocket state: COMPLETED (disconnected)")
                    self.isConnected = false
                    
                @unknown default:
                    print("❓ WebSocket state: UNKNOWN")
                    self.isConnected = false
                }
            }
        }
    }
    
    /// Receive messages from server
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            switch result {
            case .success(let message):
                // First successful message = connection is established
                if !self.isConnected {
                    DispatchQueue.main.async {
                        self.isConnected = true
                        self.errorMessage = nil
                        self.reconnectAttempts = 0
                        print("✅ WebSocket handshake completed - connection established")
                        
                        // Now that we're connected, start ping keepalive
                        self.sendPing()
                    }
                }
                
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
                let nsError = error as NSError
                let errorDetails = "Domain: \(nsError.domain), Code: \(nsError.code), Description: \(nsError.localizedDescription)"
                print("❌ WebSocket receive error: \(errorDetails)")
                
                DispatchQueue.main.async {
                    self.isConnected = false
                    
                    // Distinguish between handshake failures and runtime disconnections
                    if nsError.code == -1011 {
                        self.errorMessage = "WebSocket handshake failed: \(nsError.localizedDescription)"
                    } else {
                        self.errorMessage = "WebSocket error: \(nsError.localizedDescription)"
                    }
                }
                
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
            // #region agent log
            let logData: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "D", "location": "BackendWebSocketClient.swift:handleMessage", "message": "Received event", "data": ["event_type": eventType ?? "nil"], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
            if let jsonData = try? JSONSerialization.data(withJSONObject: logData), let jsonString = String(data: jsonData, encoding: .utf8) {
                if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: getLogPath())) {
                    fileHandle.seekToEndOfFile()
                    fileHandle.write((jsonString + "\n").data(using: .utf8)!)
                    fileHandle.closeFile()
                }
            }
            // #endregion
            if eventType == "permission_requested", let eventData = json["data"] as? [String: Any] {
                // #region agent log
                let logData2: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "D", "location": "BackendWebSocketClient.swift:handleMessage", "message": "Permission event detected, calling handlePermissionRequest", "data": ["task_id": eventData["task_id"] as? String ?? "nil"], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
                if let jsonData2 = try? JSONSerialization.data(withJSONObject: logData2), let jsonString2 = String(data: jsonData2, encoding: .utf8) {
                    if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: getLogPath())) {
                        fileHandle.seekToEndOfFile()
                        fileHandle.write((jsonString2 + "\n").data(using: .utf8)!)
                        fileHandle.closeFile()
                    }
                }
                // #endregion
                DispatchQueue.main.async {
                    self.handlePermissionRequest(eventData)
                }
            } else {
                print("📨 Event: \(eventType ?? "unknown")")
            }
            
        case "pong":
            // Ping response - connection verified
            print("✅ Received pong - connection verified")
            // Connection is confirmed, isConnected should already be true
            break
            
        default:
            print("📨 Unknown message type: \(messageType ?? "nil")")
        }
    }
    
    /// Send ping to keep connection alive
    private func sendPing() {
        // Only send ping if actually connected
        guard isConnected, let task = webSocketTask else {
            print("⚠️ Skipping ping - not connected")
            return
        }
        
        let ping = ["type": "ping"]
        guard let data = try? JSONSerialization.data(withJSONObject: ping),
              let text = String(data: data, encoding: .utf8) else {
            return
        }
        
        let message = URLSessionWebSocketTask.Message.string(text)
        task.send(message) { [weak self] error in
            if let error = error {
                print("❌ Ping send error: \(error)")
                // If ping fails, connection might be broken
                DispatchQueue.main.async {
                    self?.isConnected = false
                }
            }
        }
        
        // Schedule next ping in 30 seconds (only if still connected)
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: false) { [weak self] _ in
            guard let self = self, self.isConnected else { return }
            self.sendPing()
        }
    }
    
    /// Schedule reconnection attempt with exponential backoff
    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        
        // Exponential backoff: 5s, 10s, 20s, 40s, max 60s
        reconnectAttempts += 1
        let baseDelay: TimeInterval = 5.0
        let maxDelay: TimeInterval = 60.0
        let delay = min(baseDelay * pow(2.0, Double(reconnectAttempts - 1)), maxDelay)
        
        print("🔄 Scheduling reconnect attempt \(reconnectAttempts) in \(delay)s")
        
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self, self.shouldReconnect else { return }
            print("🔄 Attempting reconnection...")
            self.connect()
        }
    }
    
    /// Verify connection by sending test ping and waiting for pong
    private func verifyConnection() {
        guard isConnected else { return }
        
        // Send test ping
        sendPing()
        
        // Connection is verified when we receive pong in handleMessage
        // This is handled automatically by the existing ping/pong flow
    }
    
    /// Handle permission request event
    private func handlePermissionRequest(_ data: [String: Any]) {
        // #region agent log
        let logData: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "D", "location": "BackendWebSocketClient.swift:handlePermissionRequest", "message": "handlePermissionRequest called", "data": ["data_keys": Array(data.keys)], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
        if let jsonData = try? JSONSerialization.data(withJSONObject: logData), let jsonString = String(data: jsonData, encoding: .utf8) {
            if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: getLogPath())) {
                fileHandle.seekToEndOfFile()
                fileHandle.write((jsonString + "\n").data(using: .utf8)!)
                fileHandle.closeFile()
            }
        }
        // #endregion
        guard let taskId = data["task_id"] as? String,
              let toolName = data["tool_name"] as? String else {
            // #region agent log
            let logData2: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "D", "location": "BackendWebSocketClient.swift:handlePermissionRequest", "message": "Parsing failed - missing required fields", "data": [:], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
            if let jsonData2 = try? JSONSerialization.data(withJSONObject: logData2), let jsonString2 = String(data: jsonData2, encoding: .utf8) {
                if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: getLogPath())) {
                    fileHandle.seekToEndOfFile()
                    fileHandle.write((jsonString2 + "\n").data(using: .utf8)!)
                    fileHandle.closeFile()
                }
            }
            // #endregion
            return
        }
        
        let toolArgs = (data["tool_args"] as? [String: Any]) ?? [:]
        let rationale = data["rationale"] as? String ?? ""
        
        // Convert toolArgs to string for PermissionRequest
        let toolArgsString: String
        if let jsonData = try? JSONSerialization.data(withJSONObject: toolArgs),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            toolArgsString = jsonString
        } else {
            toolArgsString = "{}"
        }
        
        permissionRequest = PermissionRequest(
            taskId: taskId,
            toolName: toolName,
            toolArgs: toolArgsString,
            rationale: rationale
        )
        
        // #region agent log
        let logData3: [String: Any] = ["sessionId": "debug-session", "runId": "test-permission-ws", "hypothesisId": "E", "location": "BackendWebSocketClient.swift:handlePermissionRequest", "message": "PermissionRequest set", "data": ["task_id": taskId, "tool_name": toolName], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
        if let jsonData3 = try? JSONSerialization.data(withJSONObject: logData3), let jsonString3 = String(data: jsonData3, encoding: .utf8) {
            if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: getLogPath())) {
                fileHandle.seekToEndOfFile()
                fileHandle.write((jsonString3 + "\n").data(using: .utf8)!)
                fileHandle.closeFile()
            }
        }
        // #endregion
        
        print("🔔 Permission request received: \(toolName) for task \(taskId)")
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

