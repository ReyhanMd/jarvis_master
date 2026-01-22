import Foundation

/// LaunchManager starts and stops Shail services via bundled scripts.
/// It expects `start_shail.sh` and `stop_shail.sh` at the repo root.
class LaunchManager {
    private let workingDir = "/Users/reyhan/jarvis_master"
    private let startScript = "start_shail.sh"
    private let stopScript = "stop_shail.sh"

    @discardableResult
    func startAll() -> Bool {
        runScript(startScript)
    }

    @discardableResult
    func stopAll() -> Bool {
        runScript(stopScript)
    }

    @discardableResult
    private func runScript(_ script: String) -> Bool {
        let scriptPath = "\(workingDir)/\(script)"
        guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
            NSLog("Script not found or not executable: \(scriptPath)")
            return false
        }

        let task = Process()
        task.launchPath = "/bin/bash"
        task.arguments = [scriptPath]
        task.currentDirectoryPath = workingDir

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe

        do {
            try task.run()
            return true
        } catch {
            NSLog("Failed to run script \(script): \(error)")
            return false
        }
    }
}
