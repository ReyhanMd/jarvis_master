import Foundation
import ServiceLauncher

enum Command: String {
    case start
    case stop
    case status
    case help
}

let args = CommandLine.arguments.dropFirst()
let command = args.first.flatMap { Command(rawValue: $0) } ?? .start
let launcher = ServiceLauncher()

switch command {
case .start:
    let code = launcher.start()
    print("Start script exited with code \(code)")
case .stop:
    let code = launcher.stop()
    print("Stop script exited with code \(code)")
case .status:
    let statuses = launcher.status()
    statuses.forEach { port, open in
        print("Port \(port): \(open ? "LISTENING" : "CLOSED")")
    }
case .help:
    print("""
Usage: shail-launch [command]
  start   Start all Shail services (default)
  stop    Stop all Shail services
  status  Show port status for core services
  help    Show this help
""")
}
