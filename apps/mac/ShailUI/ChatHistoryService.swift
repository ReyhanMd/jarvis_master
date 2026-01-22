import Foundation

/// Service to fetch and store chat history via backend API.
class ChatHistoryService {
    static let shared = ChatHistoryService()
    private let baseURL = URL(string: "http://localhost:8000")!
    private init() {}

    func fetchHistory() async throws -> [ChatMessage] {
        let url = baseURL.appendingPathComponent("chat/history")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode([ChatMessage].self, from: data)
    }

    func appendMessage(_ message: ChatMessage) async {
        // Optional: cache locally if needed
    }
}
