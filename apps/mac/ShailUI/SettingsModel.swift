import Foundation

struct APISettings: Codable {
    var baseURL: String = "http://localhost:8000"
}

struct LLMSettings: Codable {
    var model: String = "gemini-2.0-flash"
    var temperature: Double = 0.7
}

struct PermissionSettings: Codable {
    var autoApproveCategories: [String] = []
}

struct AppearanceSettings: Codable {
    var theme: String = "system"
}

struct AdvancedSettings: Codable {
    var loggingEnabled: Bool = false
}

struct NativeServicesSettings: Codable {
    var autoStart: Bool = true
    var bufferWindowSeconds: Double = 300
    var frameIntervalSeconds: Double = 2
    var consentRequired: Bool = true
}

struct ShailSettings: Codable {
    var api = APISettings()
    var llm = LLMSettings()
    var permissions = PermissionSettings()
    var appearance = AppearanceSettings()
    var advanced = AdvancedSettings()
    var native = NativeServicesSettings()
}
