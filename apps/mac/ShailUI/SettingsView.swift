import SwiftUI

struct SettingsView: View {
    @ObservedObject var manager = SettingsManager.shared
    @Environment(\.dismiss) var dismiss
    
    var body: some View {
        TabView {
            GeneralSettingsView(settings: $manager.settings)
                .tabItem { Text("General") }
            LLMSettingsView(settings: $manager.settings)
                .tabItem { Text("LLM") }
            PermissionSettingsView(settings: $manager.settings)
                .tabItem { Text("Permissions") }
            AppearanceSettingsView(settings: $manager.settings)
                .tabItem { Text("Appearance") }
            NativeServicesSettingsView(settings: $manager.settings)
                .tabItem { Text("Native") }
            AdvancedSettingsView(settings: $manager.settings)
                .tabItem { Text("Advanced") }
        }
        .frame(minWidth: 420, minHeight: 320)
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
