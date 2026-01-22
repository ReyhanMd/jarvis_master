import SwiftUI

struct VisionContextView: View {
    let observationText: String?
    let anomalies: [String]

    init(observationText: String? = nil, anomalies: [String] = []) {
        self.observationText = observationText
        self.anomalies = anomalies
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Vision Context")
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundColor(.secondary)

            if let text = observationText, !text.isEmpty {
                Text(text)
                    .font(.caption)
                    .foregroundColor(.primary)
            } else {
                Text("No vision observations yet.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            if !anomalies.isEmpty {
                Text("Anomalies: " + anomalies.joined(separator: ", "))
                    .font(.caption2)
                    .foregroundColor(.orange)
            }
        }
        .padding(8)
        .background(Color.gray.opacity(0.08))
        .cornerRadius(8)
    }
}
