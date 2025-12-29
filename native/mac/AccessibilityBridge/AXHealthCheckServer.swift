import Foundation
import Network

/// Simple HTTP health check server for AccessibilityBridge
actor AXHealthCheckServer {
    private var listener: NWListener?
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
            
            listener = try NWListener(using: parameters, on: NWEndpoint.Port(rawValue: port)!)
            
            listener?.newConnectionHandler = { [weak self] connection in
                Task {
                    await self?.handleConnection(connection)
                }
            }
            
            listener?.start(queue: .main)
            isRunning = true
            print("🏥 Health check server listening on port \(port)")
            
        } catch {
            print("❌ Failed to start health check server: \(error)")
        }
    }
    
    func stop() {
        listener?.cancel()
        isRunning = false
    }
    
    private func handleConnection(_ connection: NWConnection) {
        connection.start(queue: .main)
        
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1024) { [weak self] data, _, isComplete, error in
            if let error = error {
                print("❌ Health check connection error: \(error)")
                connection.cancel()
                return
            }
            
            if let data = data, !data.isEmpty {
                let request = String(data: data, encoding: .utf8) ?? ""
                
                // Simple HTTP request parser
                if request.contains("GET /health") || request.contains("GET /") {
                    let response = self?.createHealthResponse() ?? ""
                    if let responseData = response.data(using: .utf8) {
                        connection.send(content: responseData, completion: .contentProcessed { error in
                            if let error = error {
                                print("❌ Health check send error: \(error)")
                            }
                            connection.cancel()
                        })
                    }
                } else {
                    connection.cancel()
                }
            }
            
            if isComplete {
                connection.cancel()
            }
        }
    }
    
    nonisolated private func createHealthResponse() -> String {
        let json: [String: Any] = [
            "status": "healthy",
            "service": "AccessibilityBridge",
            "port": 8766,
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "uptime": ProcessInfo.processInfo.systemUptime
        ]
        
        let jsonData = try? JSONSerialization.data(withJSONObject: json, options: .prettyPrinted)
        let jsonString = String(data: jsonData ?? Data(), encoding: .utf8) ?? "{}"
        
        return """
        HTTP/1.1 200 OK
        Content-Type: application/json
        Content-Length: \(jsonString.utf8.count)
        Connection: close
        
        \(jsonString)
        """
    }
}

