import SwiftUI

struct DesktopListView: View {
    @ObservedObject var manager: DesktopManager
    var onSelect: (String) -> Void
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Desktops")
                .font(.headline)
            ForEach(manager.desktops, id: \.self) { desk in
                HStack {
                    Text(desk)
                    Spacer()
                    if desk == manager.activeDesktop {
                        Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture {
                    manager.switchTo(desk)
                    onSelect(desk)
                }
                Divider()
            }
        }
        .padding()
    }
}
