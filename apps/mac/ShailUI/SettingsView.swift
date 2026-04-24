import SwiftUI

struct SettingsView: View {
    @ObservedObject var manager = SettingsManager.shared
    @Environment(\.dismiss) var dismiss

    var body: some View {
        TabView {
            ServicesSettingsView()
                .tabItem { Label("Services", systemImage: "bolt.fill") }
            GeneralSettingsView(settings: $manager.settings)
                .tabItem { Label("General", systemImage: "gear") }
            LLMSettingsView(settings: $manager.settings)
                .tabItem { Label("LLM", systemImage: "brain") }
            PermissionSettingsView(settings: $manager.settings)
                .tabItem { Label("Permissions", systemImage: "lock.shield") }
            AppearanceSettingsView(settings: $manager.settings)
                .tabItem { Label("Appearance", systemImage: "paintbrush") }
            NativeServicesSettingsView(settings: $manager.settings)
                .tabItem { Label("Native", systemImage: "camera.metering.matrix") }
            AdvancedSettingsView(settings: $manager.settings)
                .tabItem { Label("Advanced", systemImage: "wrench.and.screwdriver") }
            AccountSettingsView(settings: $manager.settings)
                .tabItem { Label("Account", systemImage: "key.fill") }
        }
        .frame(minWidth: 480, minHeight: 360)
    }
}

struct ServicesSettingsView: View {
    @ObservedObject private var launcher = ServiceLauncher.shared
    @State private var repoPathInput: String = ""

    var body: some View {
        Form {
            Section("Repo Path") {
                if launcher.hasValidPath {
                    HStack {
                        Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
                        Text(launcher.repoRoot)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Change…") { launcher.promptForRepoPath() }
                    }
                } else {
                    HStack {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
                        Text("Repo not found — start_shail.sh missing")
                            .font(.caption)
                            .foregroundColor(.orange)
                        Spacer()
                        Button("Choose Folder…") { launcher.promptForRepoPath() }
                    }
                }
            }

            Section("Status") {
                HStack {
                    Circle()
                        .fill(launcher.isRunning ? Color.green : Color.red)
                        .frame(width: 8, height: 8)
                    Text(launcher.statusMessage)
                        .foregroundColor(.primary)
                    Spacer()
                    if launcher.isRunning {
                        Button("Stop") { launcher.stopAll() }
                            .foregroundColor(.red)
                    } else {
                        Button("Start") { launcher.startAll() }
                            .disabled(!launcher.hasValidPath)
                            .buttonStyle(.borderedProminent)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct GeneralSettingsView: View {
    @Binding var settings: ShailSettings
    var body: some View {
        Form {
            TextField("API URL", text: $settings.api.baseURL)
        }
        .padding()
    }
}

struct LLMSettingsView: View {
    @Binding var settings: ShailSettings
    var body: some View {
        Form {
            TextField("Model", text: $settings.llm.model)
            Slider(value: $settings.llm.temperature, in: 0...1, step: 0.1) {
                Text("Temperature")
            }
            Text(String(format: "%.1f", settings.llm.temperature))
        }
        .padding()
    }
}

struct PermissionSettingsView: View {
    @Binding var settings: ShailSettings
    @State private var newCategory: String = ""
    var body: some View {
        Form {
            HStack {
                TextField("Add auto-approve category", text: $newCategory)
                Button("Add") {
                    guard !newCategory.isEmpty else { return }
                    settings.permissions.autoApproveCategories.append(newCategory)
                    newCategory = ""
                }
            }
            List {
                ForEach(settings.permissions.autoApproveCategories, id: \.self) { cat in
                    Text(cat)
                }
            }
        }
        .padding()
    }
}

struct AppearanceSettingsView: View {
    @Binding var settings: ShailSettings
    var body: some View {
        Form {
            Picker("Theme", selection: $settings.appearance.theme) {
                Text("System").tag("system")
                Text("Light").tag("light")
                Text("Dark").tag("dark")
            }
        }
        .padding()
    }
}

struct AdvancedSettingsView: View {
    @Binding var settings: ShailSettings
    var body: some View {
        Form {
            Toggle("Enable logging", isOn: $settings.advanced.loggingEnabled)
        }
        .padding()
    }
}

struct AccountSettingsView: View {
    @Binding var settings: ShailSettings
    @State private var showKey = false

    var body: some View {
        Form {
            Section("API Key") {
                HStack {
                    if showKey {
                        TextField("shail_...", text: $settings.apiKey)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))
                    } else {
                        SecureField("shail_...", text: $settings.apiKey)
                            .textFieldStyle(.roundedBorder)
                    }
                    Button(showKey ? "Hide" : "Show") { showKey.toggle() }
                }
                Text("Get your key from the SHAIL extension → Options → Account → \"Add This Browser\"")
                    .font(.caption).foregroundColor(.secondary)
            }
            if !settings.apiKey.isEmpty {
                Section("Status") {
                    Label("API key set — memories isolated to your account",
                          systemImage: "checkmark.seal.fill").foregroundColor(.green)
                }
            }
        }
        .padding()
    }
}

struct NativeServicesSettingsView: View {
    @Binding var settings: ShailSettings
    var body: some View {
        Form {
            Toggle("Auto-start native services", isOn: $settings.native.autoStart)
            Toggle("Require consent for capture", isOn: $settings.native.consentRequired)
            Stepper(value: $settings.native.bufferWindowSeconds, in: 60...900, step: 30) {
                Text("Buffer window: \(Int(settings.native.bufferWindowSeconds))s")
            }
            Stepper(value: $settings.native.frameIntervalSeconds, in: 1...10, step: 1) {
                Text("Frame interval: \(Int(settings.native.frameIntervalSeconds))s")
            }
        }
        .padding()
    }
}
