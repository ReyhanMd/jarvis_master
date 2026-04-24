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

    private func authHeader() -> [String: String] {
        let key = SettingsManager.shared.settings.apiKey
        guard !key.isEmpty else { return [:] }
        return ["Authorization": "Bearer \(key)"]
    }

    func submitTask(text: String, mode: String? = "auto", desktopId: String? = nil) async throws -> TaskSubmissionResponse {
        let url = baseURL.appendingPathComponent("tasks")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authHeader().forEach { request.setValue($1, forHTTPHeaderField: $0) }
        request.httpBody = try JSONEncoder().encode(TaskSubmissionRequest(text: text, mode: mode, desktopId: desktopId))

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(TaskSubmissionResponse.self, from: data)
    }

    func fetchStatus(taskId: String) async throws -> TaskStatusResponse {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)")
        var request = URLRequest(url: url)
        authHeader().forEach { request.setValue($1, forHTTPHeaderField: $0) }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(TaskStatusResponse.self, from: data)
    }

    func fetchResults(taskId: String) async throws -> TaskResultPayload? {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)/results")
        var request = URLRequest(url: url)
        authHeader().forEach { request.setValue($1, forHTTPHeaderField: $0) }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        let wrapper = try JSONDecoder().decode([String: TaskResultPayload].self, from: data)
        return wrapper["result"]
    }
}
