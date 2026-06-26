import Foundation
import AppKit

/// LocalFilesService — bridges the macOS file picker to the backend's
/// /browser/chat/files/* endpoints. The Swift side picks an absolute path
/// via NSOpenPanel and POSTs it; the backend walks, chunks, and embeds.
class LocalFilesService {
    static let shared = LocalFilesService()
    private let baseURL = "http://localhost:8000"
    private init() {}

    private func authHeader() -> [String: String] {
        let key = SettingsManager.shared.settings.apiKey
        guard !key.isEmpty else { return [:] }
        return ["Authorization": "Bearer \(key)"]
    }

    // MARK: - NSOpenPanel pickers

    /// Show a folder picker (security-scoped). Returns absolute path or nil.
    @MainActor
    func pickFolder(prompt: String = "Ingest into SHAIL memory") -> String? {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = prompt
        panel.message = "Pick a folder. SHAIL will walk it recursively, skipping node_modules / .git / hidden files."
        let response = panel.runModal()
        guard response == .OK, let url = panel.url else { return nil }
        return url.path
    }

    /// Show a multi-file picker. Returns absolute paths or empty array.
    @MainActor
    func pickFiles(prompt: String = "Ingest into SHAIL memory") -> [String] {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.prompt = prompt
        let response = panel.runModal()
        guard response == .OK else { return [] }
        return panel.urls.map { $0.path }
    }

    // MARK: - Backend calls

    struct IngestResponse: Codable {
        let ingested: Int
        let skipped: Int
        let files_seen: Int
        let errors: [String]
    }

    /// POST /browser/chat/files/ingest — walk paths, embed, persist.
    func ingest(paths: [String], maxFiles: Int = 500) async throws -> IngestResponse {
        guard let url = URL(string: "\(baseURL)/browser/chat/files/ingest") else {
            throw LocalFilesError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authHeader().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.httpBody = try JSONEncoder().encode(["paths": paths,
                                                  "max_files": maxFiles] as [String: Any])

        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.validate(resp, data: data)
        return try JSONDecoder().decode(IngestResponse.self, from: data)
    }

    struct WatchResponse: Codable {
        let ok: Bool
        let path: String?
        let status: String?
        let error: String?
    }

    struct WatchListItem: Codable {
        let user_id: String
        let path: String
        let created_at: String
        let last_event_at: String?
        let event_count: Int
    }

    struct WatchListResponse: Codable {
        let watches: [WatchListItem]
    }

    /// POST /browser/chat/files/watch — start watchdog on absolute folder.
    func startWatch(path: String) async throws -> WatchResponse {
        guard let url = URL(string: "\(baseURL)/browser/chat/files/watch") else {
            throw LocalFilesError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authHeader().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.httpBody = try JSONEncoder().encode(["path": path])

        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.validate(resp, data: data)
        return try JSONDecoder().decode(WatchResponse.self, from: data)
    }

    /// DELETE /browser/chat/files/watch?path=... — stop a running watcher.
    func stopWatch(path: String) async throws -> WatchResponse {
        guard let encoded = path.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let url = URL(string: "\(baseURL)/browser/chat/files/watch?path=\(encoded)") else {
            throw LocalFilesError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "DELETE"
        authHeader().forEach { req.setValue($1, forHTTPHeaderField: $0) }

        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.validate(resp, data: data)
        return try JSONDecoder().decode(WatchResponse.self, from: data)
    }

    /// GET /browser/chat/files/watch — list this user's active watches.
    func listWatches() async throws -> [WatchListItem] {
        guard let url = URL(string: "\(baseURL)/browser/chat/files/watch") else {
            throw LocalFilesError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        authHeader().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.validate(resp, data: data)
        let listResp = try JSONDecoder().decode(WatchListResponse.self, from: data)
        return listResp.watches
    }

    // MARK: - Helpers

    private static func validate(_ resp: URLResponse, data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { throw LocalFilesError.invalidResponse }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw LocalFilesError.httpError(http.statusCode, msg)
        }
    }
}

enum LocalFilesError: LocalizedError {
    case invalidURL
    case invalidResponse
    case httpError(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:           return "Invalid URL"
        case .invalidResponse:      return "Invalid response"
        case .httpError(let c, let m): return "HTTP \(c): \(m)"
        }
    }
}
