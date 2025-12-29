import Foundation

/// Service for communicating with SHAIL backend API
class ChatService {
    static let shared = ChatService()
    
    private let baseURL = "http://localhost:8000"
    
    private init() {}
    
    /// Sends a chat message to the backend
    func sendMessage(_ text: String) async throws -> ChatResponse {
        guard let url = URL(string: "\(baseURL)/chat") else {
            throw ChatServiceError.invalidURL
        }
        
        let request = ChatRequest(text: text, attachments: nil)
        
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            urlRequest.httpBody = try JSONEncoder().encode(request)
        } catch {
            throw ChatServiceError.encodingError(error)
        }
        
        let (data, response) = try await URLSession.shared.data(for: urlRequest)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw ChatServiceError.invalidResponse
        }
        
        guard (200...299).contains(httpResponse.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw ChatServiceError.httpError(httpResponse.statusCode, errorMessage)
        }
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try decoder.decode(ChatResponse.self, from: data)
        } catch {
            throw ChatServiceError.decodingError(error)
        }
    }
    
    /// Checks if the backend is available
    func checkHealth() async -> Bool {
        guard let url = URL(string: "\(baseURL)/health") else {
            return false
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 2.0
        
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                return (200...299).contains(httpResponse.statusCode)
            }
        } catch {
            return false
        }
        
        return false
    }
}

/// Chat request model matching backend API
struct ChatRequest: Codable {
    let text: String
    let attachments: [Attachment]?
}

/// Chat response model matching backend API
struct ChatResponse: Codable {
    let text: String
    let model: String
    let timestamp: Date?
}

/// Attachment model
struct Attachment: Codable {
    let name: String
    let mime_type: String?
    let content_b64: String?
}

/// Chat service errors
enum ChatServiceError: LocalizedError {
    case invalidURL
    case encodingError(Error)
    case invalidResponse
    case httpError(Int, String)
    case decodingError(Error)
    
    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .encodingError(let error):
            return "Encoding error: \(error.localizedDescription)"
        case .invalidResponse:
            return "Invalid response"
        case .httpError(let code, let message):
            return "HTTP error \(code): \(message)"
        case .decodingError(let error):
            return "Decoding error: \(error.localizedDescription)"
        }
    }
}

