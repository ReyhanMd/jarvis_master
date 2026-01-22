// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "shail-launch",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "shail-launch", targets: ["shail-launch"])
    ],
    targets: [
        .executableTarget(
            name: "shail-launch",
            dependencies: ["ServiceLauncher"]
        ),
        .target(
            name: "ServiceLauncher",
            dependencies: []
        )
    ]
)
