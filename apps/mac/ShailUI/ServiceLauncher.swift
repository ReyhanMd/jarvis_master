import Foundation
import AppKit
import Security

/// Finds the SHAIL repo root and starts/stops all backend services via start_shail.sh / stop_shail.sh.
/// Path is auto-detected on first launch and persisted in UserDefaults.
class ServiceLauncher: ObservableObject {
    static let shared = ServiceLauncher()

    @Published var isRunning: Bool = false
    @Published var statusMessage: String = "Stopped"
    /// Last 30 lines of stdout/stderr from start_shail.sh — surfaced in offline UI.
    @Published var lastError: String = ""
    /// Last /health response body — populated after waitForHealth succeeds or fails.
    @Published var lastHealthSnapshot: String = ""

    private let userDefaultsKey = "shail_repo_root"

    private let candidatePaths: [String] = [
        NSHomeDirectory() + "/jarvis_master",
        NSHomeDirectory() + "/shail_master",
        NSHomeDirectory() + "/SHAIL",
        NSHomeDirectory() + "/Documents/jarvis_master",
    ]

    /// Persisted repo root — auto-detected or user-configured.
    var repoRoot: String {
        get {
            if let saved = UserDefaults.standard.string(forKey: userDefaultsKey), isValidRoot(saved) {
                return saved
            }
            let found = candidatePaths.first { isValidRoot($0) } ?? ""
            if !found.isEmpty { UserDefaults.standard.set(found, forKey: userDefaultsKey) }
            return found
        }
        set {
            UserDefaults.standard.set(newValue, forKey: userDefaultsKey)
            objectWillChange.send()
        }
    }

    var hasValidPath: Bool { isValidRoot(repoRoot) }

    // MARK: - Public API

    func startAll() {
        guard hasValidPath else {
            statusMessage = "Repo path not found — configure in Settings"
            return
        }
        if isPort8000InUse() {
            // Backend already running — delegate remaining services to the API
            isRunning = true
            statusMessage = "Running"
            startManagedServicesViaAPI()
            return
        }
        // Cold start: launch FastAPI first via script, then delegate the rest
        statusMessage = "Starting services…"
        lastError = ""
        runScript("start_shail.sh") { [weak self] success, output in
            guard let self else { return }
            let lines = output.components(separatedBy: "\n")
            let tail = lines.suffix(30).joined(separator: "\n")
            DispatchQueue.main.async { self.lastError = tail }
            if success {
                self.waitForHealth()
            } else {
                DispatchQueue.main.async {
                    self.isRunning = false
                    self.statusMessage = "Failed to start — see details below"
                }
            }
        }
    }

    /// Called after FastAPI is confirmed healthy — delegates Ollama + worker start to /system/start.
    private func startManagedServicesViaAPI() {
        guard let url = URL(string: "http://localhost:8000/system/start") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        if let key = UserDefaults.standard.string(forKey: "shail_api_key") {
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        }
        // Fire-and-forget; BackendManager.check() will pick up per-service status on next tick
        URLSession.shared.dataTask(with: req) { _, _, _ in
            DispatchQueue.global().asyncAfter(deadline: .now() + 3) {
                BackendManager.shared.check()
            }
        }.resume()
    }

    func stopAll() {
        guard hasValidPath else { return }
        statusMessage = "Stopping managed services…"
        // First: stop Ollama + worker via API
        if isPort8000InUse(), let url = URL(string: "http://localhost:8000/system/stop") {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            if let key = UserDefaults.standard.string(forKey: "shail_api_key") {
                req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            }
            let sem = DispatchSemaphore(value: 0)
            URLSession.shared.dataTask(with: req) { _, _, _ in sem.signal() }.resume()
            sem.wait(timeout: .now() + 5)
        }
        // Then: stop FastAPI itself via script
        statusMessage = "Stopping backend…"
        runScript("stop_shail.sh") { [weak self] _, _ in
            // Belt-and-suspenders: ensure uvicorn is dead
            let kill = Process()
            kill.launchPath = "/usr/bin/pkill"
            kill.arguments = ["-f", "uvicorn"]
            kill.standardOutput = Pipe()
            kill.standardError  = Pipe()
            try? kill.run()
            kill.waitUntilExit()
            DispatchQueue.main.async {
                self?.isRunning = false
                self?.statusMessage = "Stopped"
            }
        }
    }

    // MARK: - Private health helpers

    private func isPort8000InUse() -> Bool {
        let task = Process()
        task.launchPath = "/usr/bin/lsof"
        task.arguments  = ["-ti", ":8000"]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError  = Pipe()
        guard (try? task.run()) != nil else { return false }
        task.waitUntilExit()
        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func waitForHealth(attempts: Int = 0) {
        guard attempts < 20 else {
            DispatchQueue.main.async {
                self.isRunning = false
                self.statusMessage = "Backend not responding after start"
            }
            return
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let url = URL(string: "http://127.0.0.1:8000/health") else { return }
            let sem = DispatchSemaphore(value: 0)
            var ok  = false
            var bodyStr = ""
            URLSession.shared.dataTask(with: url) { data, resp, _ in
                ok = (resp as? HTTPURLResponse).map { (200...299).contains($0.statusCode) } ?? false
                if let data = data { bodyStr = String(data: data, encoding: .utf8) ?? "" }
                sem.signal()
            }.resume()
            sem.wait()
            if ok {
                DispatchQueue.main.async {
                    self?.isRunning = true
                    self?.statusMessage = "Running"
                    self?.lastHealthSnapshot = bodyStr
                }
                self?.startManagedServicesViaAPI()
            } else {
                self?.waitForHealth(attempts: attempts + 1)
            }
        }
    }

    /// Open a folder picker so the user can point to the repo manually.
    func promptForRepoPath() {
        let panel = NSOpenPanel()
        panel.title = "Select SHAIL repo folder"
        panel.message = "Choose the folder that contains start_shail.sh"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            if response == .OK, let url = panel.url {
                self?.repoRoot = url.path
            }
        }
    }

    // MARK: - Private

    private func isValidRoot(_ path: String) -> Bool {
        FileManager.default.isExecutableFile(atPath: path + "/start_shail.sh")
    }

    private func runScript(_ name: String, completion: @escaping (Bool, String) -> Void) {
        let scriptPath = repoRoot + "/" + name
        guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
            DispatchQueue.main.async { completion(false, "Script not found or not executable: \(scriptPath)") }
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.launchPath = "/bin/bash"
            task.arguments = [scriptPath]
            task.currentDirectoryPath = self.repoRoot

            // Inject master encryption key from macOS Keychain
            var env = ProcessInfo.processInfo.environment
            env["SHAIL_TOKEN_KEY"] = self.retrieveOrCreateMasterKey()
            task.environment = env

            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe

            do {
                try task.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                let output = String(data: data, encoding: .utf8) ?? ""
                DispatchQueue.main.async { completion(task.terminationStatus == 0, output) }
            } catch {
                NSLog("[ServiceLauncher] Failed to run \(name): \(error)")
                DispatchQueue.main.async { completion(false, "Exec error: \(error.localizedDescription)") }
            }
        }
    }

    private func retrieveOrCreateMasterKey() -> String {
        let service = "shail_system"
        let account = "shail_master_key"
        
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var dataTypeRef: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &dataTypeRef)
        
        if status == errSecSuccess, let data = dataTypeRef as? Data, let keyStr = String(data: data, encoding: .utf8) {
            return keyStr
        }
        
        // Generate a new 32-byte key base64 encoded
        var bytes = [UInt8](repeating: 0, count: 32)
        let genStatus = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let newKey: String
        if genStatus == errSecSuccess {
            newKey = Data(bytes).base64EncodedString()
        } else {
            newKey = UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")
        }
        
        let attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: newKey.data(using: .utf8)!
        ]
        
        SecItemAdd(attributes as CFDictionary, nil)
        return newKey
    }
}
