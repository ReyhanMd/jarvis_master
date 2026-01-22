import Foundation

class PermissionService {
    static let shared = PermissionService()
    private let baseURL = URL(string: "http://localhost:8000")!
    private init() {}

    func fetchAwaitingApproval() async throws -> [PermissionRequest] {
        let url = baseURL.appendingPathComponent("tasks/awaiting-approval")
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        // Backend response structure assumed [{task_id, tool_name, tool_args, rationale}]
        let raw = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] ?? []
        return raw.compactMap { item in
            guard let taskId = item["task_id"] as? String,
                  let tool = item["tool_name"] as? String else { return nil }
            let args = (item["tool_args"] as? String) ?? ""
            let rationale = (item["rationale"] as? String) ?? ""
            return PermissionRequest(taskId: taskId, toolName: tool, toolArgs: args, rationale: rationale)
        }
    }

    func approve(taskId: String) async throws {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)/approve")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
    }

    func deny(taskId: String) async throws {
        let url = baseURL.appendingPathComponent("tasks/\(taskId)/deny")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
    }
}
