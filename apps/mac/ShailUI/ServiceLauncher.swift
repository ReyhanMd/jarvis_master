import Foundation
import AppKit

/// Finds the SHAIL repo root and starts/stops all backend services via start_shail.sh / stop_shail.sh.
/// Path is auto-detected on first launch and persisted in UserDefaults.
class ServiceLauncher: ObservableObject {
    static let shared = ServiceLauncher()

    @Published var isRunning: Bool = false
    @Published var statusMessage: String = "Stopped"

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
        statusMessage = "Starting services…"
        runScript("start_shail.sh") { [weak self] success in
            self?.isRunning = success
            self?.statusMessage = success ? "Running" : "Failed to start"
        }
    }

    func stopAll() {
        guard hasValidPath else { return }
        statusMessage = "Stopping…"
        runScript("stop_shail.sh") { [weak self] _ in
            self?.isRunning = false
            self?.statusMessage = "Stopped"
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

    private func runScript(_ name: String, completion: @escaping (Bool) -> Void) {
        let scriptPath = repoRoot + "/" + name
        guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
            DispatchQueue.main.async { completion(false) }
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.launchPath = "/bin/bash"
            task.arguments = [scriptPath]
            task.currentDirectoryPath = self.repoRoot

            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe

            do {
                try task.run()
                task.waitUntilExit()
                DispatchQueue.main.async { completion(task.terminationStatus == 0) }
            } catch {
                NSLog("[ServiceLauncher] Failed to run \(name): \(error)")
                DispatchQueue.main.async { completion(false) }
            }
        }
    }
}
