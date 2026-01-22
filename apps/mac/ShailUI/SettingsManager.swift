import Foundation

class SettingsManager: ObservableObject {
    static let shared = SettingsManager()
    @Published var settings: ShailSettings {
        didSet { save() }
    }
    private let key = "shail_settings"
    
    private init() {
        if let data = UserDefaults.standard.data(forKey: key),
           let decoded = try? JSONDecoder().decode(ShailSettings.self, from: data) {
            settings = decoded
        } else {
            settings = ShailSettings()
        }
    }
    
    private func save() {
        if let data = try? JSONEncoder().encode(settings) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }
}
