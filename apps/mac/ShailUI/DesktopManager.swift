import Foundation
import Combine

class DesktopManager: ObservableObject {
    @Published var desktops: [String] = ["Desktop 1", "Desktop 2"]
    @Published var activeDesktop: String = "Desktop 1"
    
    func switchTo(_ name: String) {
        if desktops.contains(name) {
            activeDesktop = name
        }
    }
    
    func addDesktop(name: String) {
        guard !desktops.contains(name) else { return }
        desktops.append(name)
    }
}
