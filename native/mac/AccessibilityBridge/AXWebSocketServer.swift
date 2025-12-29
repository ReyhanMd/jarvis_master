import Foundation
import Network

actor AXWebSocketServer {
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private let port: UInt16
    private var isRunning = false
    
    init(port: UInt16) {
        self.port = port
    }
    
    func start() async {
        guard !isRunning else { return }
        
        do {
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            
            // Configure WebSocket options
            let wsOptions = NWProtocolWebSocket.Options()
            parameters.defaultProtocolStack.applicationProtocols.insert(wsOptions, at: 0)
            
            listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: port)!)
            
            listener?.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    print("🌐 WebSocket server listening on port \(self?.port ?? 0)")
                case .failed(let error):
                    print("❌ Server failed: \(error)")
                case .cancelled:
                    print("⚠️  Server cancelled")
                default:
                    break
                }
            }
            
            listener?.newConnectionHandler = { [weak self] connection in
                Task {
                    await self?.handleNewConnection(connection)
                }
            }
            
            listener?.start(queue: .main)
            isRunning = true
            
        } catch {
            print("❌ Failed to start WebSocket server: \(error)")
        }
    }
    
    func stop() {
        listener?.cancel()
        connections.forEach { $0.cancel() }
        connections.removeAll()
        isRunning = false
    }
    
    private func handleNewConnection(_ connection: NWConnection) {
        print("🔌 New client connected")
        connections.append(connection)
        
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                print("✅ Client ready")
                Task {
                    await self?.receiveMessages(from: connection)
                }
            case .failed(let error):
                print("❌ Client connection failed: \(error)")
                Task {
                    await self?.removeConnection(connection)
                }
            case .cancelled:
                print("⚠️  Client disconnected")
                Task {
                    await self?.removeConnection(connection)
                }
            default:
                break
            }
        }
        
        connection.start(queue: .main)
    }
    
    private func receiveMessages(from connection: NWConnection) {
        connection.receiveMessage { [weak self] (data, context, isComplete, error) in
            if let error = error {
                print("❌ Receive error: \(error)")
                return
            }
            
            // Process incoming message
            if let data = data,
               let message = String(data: data, encoding: .utf8) {
                Task {
                    await self?.handleMessage(message, from: connection)
                }
            }
            
            // Continue receiving
            Task {
                await self?.receiveMessages(from: connection)
            }
        }
    }
    
    private func handleMessage(_ message: String, from connection: NWConnection) async {
        guard let jsonData = message.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let command = json["command"] as? String else {
            return
        }
        
        var response: [String: Any] = [
            "type": "command_response",
            "command": command,
            "success": false
        ]
        
        switch command {
        case "click":
            if let x = json["x"] as? Int, let y = json["y"] as? Int {
                let success = AXController.click(x: x, y: y)
                response["success"] = success
                response["x"] = x
                response["y"] = y
            } else {
                response["error"] = "Missing x or y coordinates"
            }
            
        case "type":
            if let text = json["text"] as? String {
                let success = AXController.typeText(text)
                response["success"] = success
                response["text_length"] = text.count
            } else {
                response["error"] = "Missing text parameter"
            }
            
        case "press_key":
            if let key = json["key"] as? String {
                let success = AXController.pressKey(key)
                response["success"] = success
                response["key"] = key
            } else {
                response["error"] = "Missing key parameter"
            }
            
        case "get_active_window":
            let info = AXController.getActiveWindowInfo()
            response["success"] = true
            response["window_info"] = info
            
        case "get_element_at":
            if let x = json["x"] as? Int, let y = json["y"] as? Int {
                if let elementInfo = AXController.getElementAt(x: x, y: y) {
                    response["success"] = true
                    response["element"] = elementInfo
                } else {
                    response["success"] = false
                    response["error"] = "No element found at coordinates"
                }
            } else {
                response["error"] = "Missing x or y coordinates"
            }
            
        default:
            response["error"] = "Unknown command: \(command)"
        }
        
        // Send response back to client
        await sendJSON(response, to: connection)
    }
    
    private func sendJSON(_ data: [String: Any], to connection: NWConnection) async {
        guard let jsonData = try? JSONSerialization.data(withJSONObject: data),
              let jsonString = String(data: jsonData, encoding: .utf8),
              let messageData = jsonString.data(using: .utf8) else {
            return
        }
        
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "json", metadata: [metadata])
        
        connection.send(content: messageData, contentContext: context, isComplete: true, completion: .contentProcessed({ error in
            if let error = error {
                print("❌ Failed to send response: \(error)")
            }
        }))
    }
    
    private func removeConnection(_ connection: NWConnection) {
        connections.removeAll { $0 === connection }
    }
    
    func broadcastJSON(_ data: [String: Any]) {
        guard let jsonData = try? JSONSerialization.data(withJSONObject: data),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            return
        }
        
        guard let messageData = jsonString.data(using: .utf8) else { return }
        
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "json", metadata: [metadata])
        
        for connection in connections {
            connection.send(content: messageData, contentContext: context, isComplete: true, completion: .contentProcessed({ error in
                if let error = error {
                    print("❌ Failed to send JSON: \(error)")
                }
            }))
        }
    }
}

