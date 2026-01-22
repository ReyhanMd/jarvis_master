import Foundation

struct TaskStatusResponse: Codable {
    let task_id: String?
    let status: String
    let summary: String?
    let result: TaskResultPayload?
}

struct TaskResultPayload: Codable {
    let summary: String?
    let agent: String?
    let artifacts: [String: String]?
}

struct TaskSubmissionRequest: Codable {
    let text: String
    let mode: String?
    let desktop_id: String?
    
    init(text: String, mode: String? = "auto", desktopId: String? = nil) {
        self.text = text
        self.mode = mode
        self.desktop_id = desktopId
    }
}

struct TaskSubmissionResponse: Codable {
    let task_id: String
    let status: String
    let message: String
}

class TaskService {
    static let shared = TaskService()
    private let baseURL = URL(string: "http://localhost:8000")!
    private init() {}
    
    func submitTask(text: String, mode: String? = "auto", desktopId: String? = nil) async throws -> TaskSubmissionResponse {
        // #region agent log
        let logData: [String: Any] = ["sessionId": "debug-session", "runId": "test-desktop-id", "hypothesisId": "F", "location": "TaskService.swift:submitTask", "message": "Submitting task", "data": ["text": String(text.prefix(50)), "desktopId": desktopId ?? "nil"], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
        print("🔍 [DEBUG] TaskService: Submitting task with desktopId=\(desktopId ?? "nil")")
        if let jsonData = try? JSONSerialization.data(withJSONObject: logData), let jsonString = String(data: jsonData, encoding: .utf8) {
            let logPath = "/Users/reyhan/shail_master/.cursor/debug.log"
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write((jsonString + "\n").data(using: .utf8)!)
                fileHandle.closeFile()
                print("🔍 [DEBUG] Log written")
            } else {
                // Create file
                try? jsonString.write(toFile: logPath, atomically: true, encoding: .utf8)
            }
        }
        // #endregion
        let url = baseURL.appendingPathComponent("tasks")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let taskRequest = TaskSubmissionRequest(text: text, mode: mode, desktopId: desktopId)
        // #region agent log
        if let encoded = try? JSONEncoder().encode(taskRequest), let jsonString = String(data: encoded, encoding: .utf8) {
            let logData2: [String: Any] = ["sessionId": "debug-session", "runId": "test-desktop-id", "hypothesisId": "F", "location": "TaskService.swift:submitTask", "message": "Request encoded", "data": ["json": jsonString], "timestamp": Int(Date().timeIntervalSince1970 * 1000)]
            if let jsonData2 = try? JSONSerialization.data(withJSONObject: logData2), let jsonString2 = String(data: jsonData2, encoding: .utf8) {
                if let fileHandle = try? FileHandle(forWritingTo: URL(fileURLWithPath: "/Users/reyhan/shail_master/.cursor/debug.log")) {
                    fileHandle.seekToEndOfFile()
                    fileHandle.write((jsonString2 + "\n").data(using: .utf8)!)
                    fileHandle.closeFile()
                }
            }
        }
        // #endregion
        request.httpBody = try JSONEncoder().encode(taskRequest)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(TaskSubmissionResponse.self, from: data)
    }

    func fetchStatus(taskId: String) async throws -> TaskStatusResponse {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)")
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(TaskStatusResponse.self, from: data)
    }

    func fetchResults(taskId: String) async throws -> TaskResultPayload? {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)/results")
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        let wrapper = try JSONDecoder().decode([String: TaskResultPayload].self, from: data)
        return wrapper["result"]
    }
}
