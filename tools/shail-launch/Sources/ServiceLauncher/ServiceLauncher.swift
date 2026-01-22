import Foundation

public struct ServiceLauncher {
    private let workingDir: String
    private let startScript: String
    private let stopScript: String
    private let statusPorts: [Int]

    public init(
        workingDir: String = "/Users/reyhan/shail_master",
        startScript: String = "start_shail.sh",
        stopScript: String = "stop_shail.sh",
        statusPorts: [Int] = [6379, 8080, 8081, 8082, 8083, 8000]
    ) {
        self.workingDir = workingDir
        self.startScript = startScript
        self.stopScript = stopScript
        self.statusPorts = statusPorts
    }

    @discardableResult
    public func start() -> Int32 {
        runScript(startScript)
    }

    @discardableResult
    public func stop() -> Int32 {
        runScript(stopScript)
    }

    public func status() -> [Int: Bool] {
        statusPorts.reduce(into: [Int: Bool]()) { result, port in
            result[port] = isPortOpen(port)
        }
    }

    private func runScript(_ script: String) -> Int32 {
        let path = "\(workingDir)/\(script)"
        let process = Process()
        process.launchPath = "/bin/bash"
        process.arguments = [path]
        process.currentDirectoryPath = workingDir
        process.launch()
        process.waitUntilExit()
        return process.terminationStatus
    }

    private func isPortOpen(_ port: Int) -> Bool {
        let task = Process()
        let pipe = Pipe()
        task.standardOutput = pipe
        task.launchPath = "/usr/sbin/lsof"
        task.arguments = ["-Pi", ":\(port)", "-sTCP:LISTEN", "-t"]
        task.launch()
        task.waitUntilExit()
        return task.terminationStatus == 0
    }
}
