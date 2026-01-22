import Foundation

struct ChatMessage: Identifiable, Codable {
    let id: String
    let text: String
    let role: ChatRole
    let timestamp: Date
    
    init(id: String = UUID().uuidString, text: String, role: ChatRole, timestamp: Date = Date()) {
        self.id = id
        self.text = text
        self.role = role
        self.timestamp = timestamp
    }
}

enum ChatRole: String, Codable {
    case user
    case assistant
}
