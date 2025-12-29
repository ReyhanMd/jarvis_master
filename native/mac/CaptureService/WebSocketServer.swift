import Foundation
import Network

actor WebSocketServer {
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private let port: UInt16
    private var isRunning = false
    private var messageHandler: ((Data, NWProtocolWebSocket.Metadata, NWConnection) -> Void)?
    
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
    
    func setMessageHandler(_ handler: @escaping (Data, NWProtocolWebSocket.Metadata, NWConnection) -> Void) {
        messageHandler = handler
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
        // Setup receive handler for WebSocket messages
        connection.receiveMessage { [weak self] (data, context, isComplete, error) in
            if let error = error {
                print("❌ Receive error: \(error)")
                return
            }
            
            if let data = data,
               let metadata = context?.protocolMetadata.first(where: { $0 is NWProtocolWebSocket.Metadata }) as? NWProtocolWebSocket.Metadata {
                Task {
                    await self?.messageHandler?(data, metadata, connection)
                }
            }
            
            // Continue receiving
            Task {
                await self?.receiveMessages(from: connection)
            }
        }
    }
    
    private func removeConnection(_ connection: NWConnection) {
        connections.removeAll { $0 === connection }
    }
    
    func broadcastFrame(_ frameData: Data) {
        let metadata = NWProtocolWebSocket.Metadata(opcode: .binary)
        let context = NWConnection.ContentContext(identifier: "frame", metadata: [metadata])
        
        for connection in connections {
            connection.send(content: frameData, contentContext: context, isComplete: true, completion: .contentProcessed({ error in
                if let error = error {
                    print("❌ Failed to send frame: \(error)")
                }
            }))
        }
    }
    
    func broadcastJSON(_ json: String) {
        guard let data = json.data(using: .utf8) else { return }
        
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "json", metadata: [metadata])
        
        for connection in connections {
            connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed({ error in
                if let error = error {
                    print("❌ Failed to send JSON: \(error)")
                }
            }))
        }
    }
    
    func sendJSON(_ json: String, to connection: NWConnection) {
        guard let data = json.data(using: .utf8) else { return }
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "json", metadata: [metadata])
        
        connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed({ error in
            if let error = error {
                print("❌ Failed to send JSON to client: \(error)")
            }
        }))
    }
}

