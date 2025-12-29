import Foundation
import ScreenCaptureKit
import Network
import CoreGraphics
import AppKit

@available(macOS 12.3, *)
class ScreenCaptureService {
    private var stream: SCStream?
    private var captureConfig: SCStreamConfiguration?
    private var filter: SCContentFilter?
    private var streamer: WebSocketServer?
    private var lastHeartbeat: Date = Date()
    private var frameCount: Int = 0
    
    // Maintain a short history of compressed frames (timestamp + JPEG data)
    private let historyWindowSeconds: TimeInterval = 300
    private var frameHistory: [(timestamp: Double, data: Data)] = []
    private let historyQueue = DispatchQueue(label: "com.shail.CaptureService.frameHistory")
    
    init() {}
    
    func start(streamer: WebSocketServer) async {
        self.streamer = streamer
        
        // Register message handler for frame requests
        streamer.setMessageHandler { [weak self] data, metadata, connection in
            guard let self = self else { return }
            // Only process text frames
            if metadata.opcode == .text, let data = data {
                self.handleIncomingMessage(data: data, connection: connection)
            }
        }
        
        do {
            // Get available content
            let availableContent = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
            
            guard let display = availableContent.displays.first else {
                print("❌ No displays found")
                return
            }
            
            // Configure capture
            let config = SCStreamConfiguration()
            config.width = 1920  // Downscale to 1080p for performance
            config.height = 1080
            config.minimumFrameInterval = CMTime(value: 1, timescale: 30) // 30 FPS
            config.queueDepth = 5
            config.pixelFormat = kCVPixelFormatType_32BGRA
            config.showsCursor = true
            
            self.captureConfig = config
            
            // Create content filter (capture entire display)
            let filter = SCContentFilter(display: display, excludingWindows: [])
            self.filter = filter
            
            // Create stream
            let stream = SCStream(filter: filter, configuration: config, delegate: nil)
            self.stream = stream
            
            // Add stream output
            let output = CaptureStreamOutput(service: self)
            try stream.addStreamOutput(output, type: .screen, sampleHandlerQueue: .main)
            
            // Start capture
            try await stream.startCapture()
            
            // Start heartbeat timer
            startHeartbeatTimer()
            
            print("✅ Screen capture started successfully")
            
        } catch {
            print("❌ Failed to start screen capture: \(error)")
        }
    }
    
    func stop() async {
        do {
            try await stream?.stopCapture()
            print("⏹️  Screen capture stopped")
        } catch {
            print("❌ Error stopping capture: \(error)")
        }
    }
    
    func handleFrame(_ sampleBuffer: CMSampleBuffer) {
        guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            return
        }
        
        frameCount += 1
        
        // Convert to CGImage
        let ciImage = CIImage(cvImageBuffer: imageBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else {
            return
        }
        
        // Compress and send
        if let jpegData = compressToJPEG(cgImage, quality: 0.5) {
            // Store in history before broadcasting
            historyQueue.async { [weak self] in
                self?.appendFrameToHistory(jpegData)
            }
            Task {
                await streamer?.broadcastFrame(jpegData)
            }
        }
    }
    
    private func compressToJPEG(_ image: CGImage, quality: Double) -> Data? {
        let bitmapRep = NSBitmapImageRep(cgImage: image)
        return bitmapRep.representation(
            using: .jpeg,
            properties: [.compressionFactor: quality]
        )
    }
    
    private func appendFrameToHistory(_ data: Data) {
        let now = Date().timeIntervalSince1970
        frameHistory.append((timestamp: now, data: data))
        
        // Prune old frames
        let cutoff = now - historyWindowSeconds
        while let first = frameHistory.first, first.timestamp < cutoff {
            frameHistory.removeFirst()
        }
        
        // Optional safeguard to prevent unbounded growth
        let maxFrames = 900 // ~30fps * 30s equivalent; history pruning keeps older frames trimmed
        if frameHistory.count > maxFrames {
            frameHistory.removeFirst(frameHistory.count - maxFrames)
        }
    }
    
    private func handleIncomingMessage(data: Data, connection: NWConnection) {
        guard
            let json = try? JSONSerialization.jsonObject(with: data, options: []),
            let dict = json as? [String: Any],
            let type = dict["type"] as? String
        else {
            return
        }
        
        if type == "request_frames" {
            handleFrameRequest(dict, connection: connection)
        }
    }
    
    private func handleFrameRequest(_ message: [String: Any], connection: NWConnection) {
        let requestId = (message["request_id"] as? String) ?? UUID().uuidString
        let startTs = message["start_ts"] as? Double ?? 0
        let endTs = message["end_ts"] as? Double ?? Date().timeIntervalSince1970
        let fps = message["fps"] as? Double ?? 2.0
        let maxFrames = message["max_frames"] as? Int ?? 10
        
        // Down-sample frames to requested fps within the time range
        let interval = fps > 0 ? 1.0 / fps : 0.5
        let filtered: [(timestamp: Double, data: Data)] = historyQueue.sync {
            let inRange = frameHistory.filter { $0.timestamp >= startTs && $0.timestamp <= endTs }
            var selected: [(timestamp: Double, data: Data)] = []
            var lastSelectedTime = -Double.greatestFiniteMagnitude
            for frame in inRange {
                if frame.timestamp - lastSelectedTime >= interval {
                    selected.append(frame)
                    lastSelectedTime = frame.timestamp
                    if selected.count >= maxFrames { break }
                }
            }
            return selected
        }
        
        let framesPayload: [[String: Any]] = filtered.map { frame in
            [
                "ts": frame.timestamp,
                "mime": "image/jpeg",
                "data_b64": frame.data.base64EncodedString()
            ]
        }
        
        let response: [String: Any] = [
            "type": "frames_response",
            "request_id": requestId,
            "frames": framesPayload,
            "status": "ok"
        ]
        
        if
            let jsonData = try? JSONSerialization.data(withJSONObject: response),
            let jsonString = String(data: jsonData, encoding: .utf8)
        {
            streamer?.sendJSON(jsonString, to: connection)
        }
    }
    
    private func startHeartbeatTimer() {
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            
            let heartbeat: [String: Any] = [
                "type": "heartbeat",
                "timestamp": ISO8601DateFormatter().string(from: Date()),
                "frames_captured": self.frameCount,
                "uptime_seconds": Date().timeIntervalSince(self.lastHeartbeat)
            ]
            
            if let jsonData = try? JSONSerialization.data(withJSONObject: heartbeat),
               let jsonString = String(data: jsonData, encoding: .utf8) {
                Task {
                    await self.streamer?.broadcastJSON(jsonString)
                }
            }
        }
    }
}

@available(macOS 12.3, *)
class CaptureStreamOutput: NSObject, SCStreamOutput {
    private weak var service: ScreenCaptureService?
    
    init(service: ScreenCaptureService) {
        self.service = service
    }
    
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { return }
        service?.handleFrame(sampleBuffer)
    }
}

