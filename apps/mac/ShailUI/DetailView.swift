import SwiftUI

struct DetailView: View {
    @EnvironmentObject var coordinator: ViewCoordinator
    
    // Simulating "Desktops"
    let desktopApps = ["SolidWorks", "MATLAB", "Excel", "Chrome"]
    
    var body: some View {
        VStack(spacing: 0) {
            // Top Taskbar (Blue strip)
            HStack {
                ForEach(desktopApps, id: \.self) { app in
                    VStack {
                        Image(systemName: "app.fill") // Placeholder icon
                            .foregroundColor(.white)
                        Text(app)
                            .font(.caption2)
                            .foregroundColor(.white)
                    }
                    .padding(8)
                    .background(coordinator.activeDesktop == app ? Color.white.opacity(0.3) : Color.clear)
                    .cornerRadius(8)
                    .onTapGesture {
                        coordinator.activeDesktop = app
                    }
                }
                
                Spacer()
                
                // Master Access
                Button(action: { print("Summon Gemini 3 Pro") }) {
                    Image(systemName: "brain.head.profile")
                        .foregroundColor(.white)
                }
            }
            .padding()
            .background(Color.blue)
            
            // Main Pane (Software capture placeholder + Chat Overlay)
            ZStack {
                Color.white // Background for "App Window"
                
                VStack {
                    Spacer()
                    Text("Active Desktop: \(coordinator.activeDesktop ?? "None")")
                        .font(.largeTitle)
                        .foregroundColor(.gray.opacity(0.5))
                    Spacer()
                }
                
                // Floating Chat Interface for this specific desktop
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        VStack(alignment: .trailing) {
                            Text("Agent: I'm running a simulation on this desktop.")
                                .padding()
                                .background(Color.orange.opacity(0.2))
                                .cornerRadius(12)
                            
                            Button("Go to Bird's Eye") {
                                coordinator.showBirdsEye()
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        .padding()
                    }
                }
            }
        }
        .frame(minWidth: 800, minHeight: 600)
        // Gesture to go to Bird's Eye (3-finger drag down simulated by swipe down ?)
        .gesture(DragGesture().onEnded { value in
            if value.translation.height > 100 {
                coordinator.showBirdsEye()
            }
        })
    }
}
