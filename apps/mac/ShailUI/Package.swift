// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "ShailUI",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(
            name: "ShailUI",
            targets: ["ShailUI"]),
    ],
    targets: [
        .executableTarget(
            name: "ShailUI",
            path: ".",
            exclude: ["Preview Content"], // Exclude Xcode preview assets if any
            sources: [
                "ShailApp.swift",
                "ContentView.swift",
                "ViewCoordinator.swift",
                "QuickPopupView.swift",
                "ChatOverlayView.swift",
                "DetailView.swift",
                "BirdsEyeView.swift",
                "GraphWebView.swift",
                "VisualEffectBlur.swift",
                "WindowManager.swift",
                "GlobalInputListener.swift",
                "PermissionStatusView.swift",
                "ChatService.swift",
                "BackendWebSocketClient.swift",
                "ChatMessage.swift",
                "ChatHistoryService.swift",
                "ChatHistoryView.swift",
                "TaskService.swift",
                "TaskResultView.swift",
                "PermissionRequestView.swift",
                "PermissionService.swift",
                "SettingsModel.swift",
                "SettingsManager.swift",
                "SettingsView.swift",
                "DesktopManager.swift",
                "DesktopListView.swift"
            ],
            resources: [
                .process("Resources")
            ]
        )
    ]
)
