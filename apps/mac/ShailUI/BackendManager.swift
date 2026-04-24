import Foundation

class BackendManager: ObservableObject {
    static let shared = BackendManager()
    @Published var isAvailable: Bool = false

    private var timer: Timer?

    private init() {}

    func startMonitoring() {
        check()
        timer = Timer.scheduledTimer(withTimeInterval: 10.0, repeats: true) { [weak self] _ in
            self?.check()
        }
    }

    func stopMonitoring() {
        timer?.invalidate()
        timer = nil
    }

    func check() {
        Task {
            let ok = await Self.ping()
            await MainActor.run { self.isAvailable = ok }
        }
    }

    private static func ping() async -> Bool {
        guard let url = URL(string: "http://localhost:8000/health") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 3.0
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse,
              (200...299).contains(http.statusCode) else { return false }
        return true
    }
}
