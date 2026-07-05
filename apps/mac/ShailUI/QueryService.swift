import Foundation

// MARK: - Models

struct QueryRequest: Encodable {
    let text: String
    let history: [[String: String]]
}

struct QueryResponse: Decodable {
    let answer: String
    let tier_used: String
    let task_id: String?
    // backward-compat: server also returns `.text`
    let text: String?
    let sources: [WebSource]?
    let used_web: Bool?

    var resolvedAnswer: String { answer.isEmpty ? (text ?? "") : answer }
    var resolvedSources: [WebSource] { sources ?? [] }
}

// MARK: - SSE token event from /query/stream

private struct SSEToken: Decodable {
    let token: String?
    let done: Bool?
    let answer: String?
    let error: String?
    let message: String?
    let sources: [WebSource]?
}

/// Bundle returned from streaming submit — full answer + collected sources.
struct StreamingResult {
    let answer: String
    let sources: [WebSource]
}

// MARK: - Service

final class QueryService {
    static let shared = QueryService()
    private init() {}

    private let baseURL = URL(string: "http://localhost:8000")!

    // MARK: - Auth helper

    private func authHeaders() -> [String: String] {
        let key = SettingsManager.shared.settings.apiKey
        guard !key.isEmpty else { return [:] }
        return ["Authorization": "Bearer \(key)"]
    }

    // MARK: - Non-streaming (fallback)

    func submit(text: String, history: [[String: String]] = []) async throws -> QueryResponse {
        let url = baseURL.appendingPathComponent("query")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        for (k, v) in authHeaders() { request.setValue(v, forHTTPHeaderField: k) }
        request.timeoutInterval = 90
        request.httpBody = try JSONEncoder().encode(QueryRequest(text: text, history: history))

        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            let body = String(data: data, encoding: .utf8) ?? "(no body)"
            throw URLError(.badServerResponse,
                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body)"])
        }
        return try JSONDecoder().decode(QueryResponse.self, from: data)
    }

    // MARK: - Streaming (SSE) via /query/stream

    /// Posts to /query/stream and fires `onToken` on MainActor for every arriving
    /// token. Returns the full assembled answer when the server sends `"done":true`.
    /// Throws on network error or backend `"error"` SSE event.
    func submitStreaming(
        text: String,
        history: [[String: String]] = [],
        onToken: @MainActor @escaping (String) -> Void,
        onSources: (@MainActor ([WebSource]) -> Void)? = nil
    ) async throws -> StreamingResult {
        let url = baseURL.appendingPathComponent("query/stream")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        for (k, v) in authHeaders() { req.setValue(v, forHTTPHeaderField: k) }
        req.timeoutInterval = 120
        req.httpBody = try JSONEncoder().encode(QueryRequest(text: text, history: history))

        let (byteStream, response) = try await URLSession.shared.bytes(for: req)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw URLError(.badServerResponse,
                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode)"])
        }

        var fullAnswer = ""
        var lineBuffer  = ""
        var collectedSources: [WebSource] = []

        for try await byte in byteStream {
            guard let ch = String(bytes: [byte], encoding: .utf8) else { continue }
            lineBuffer += ch

            // Process every complete line
            while let nlRange = lineBuffer.range(of: "\n") {
                let line = String(lineBuffer[lineBuffer.startIndex ..< nlRange.lowerBound])
                lineBuffer = String(lineBuffer[nlRange.upperBound...])

                guard line.hasPrefix("data: ") else { continue }
                let jsonStr = String(line.dropFirst(6))
                guard let data = jsonStr.data(using: .utf8),
                      let evt  = try? JSONDecoder().decode(SSEToken.self, from: data) else { continue }

                if let errKind = evt.error {
                    throw URLError(.badServerResponse,
                        userInfo: [NSLocalizedDescriptionKey: evt.message ?? errKind])
                }
                if let srcs = evt.sources, !srcs.isEmpty {
                    collectedSources = srcs
                    if let cb = onSources { await cb(srcs) }
                }
                if let tok = evt.token, !tok.isEmpty {
                    fullAnswer += tok
                    await onToken(tok)
                }
                if evt.done == true {
                    return StreamingResult(answer: fullAnswer, sources: collectedSources)
                }
            }
        }
        return StreamingResult(answer: fullAnswer, sources: collectedSources)
    }
}
