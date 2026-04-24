import SwiftUI

enum ShailTheme {
    // MARK: - Colors (Section 9 of SHAIL UI/UX Manifesto)
    static let primaryBlue   = Color(hex: "#3A8DFF")
    static let secondaryBlue = Color(hex: "#9AD0FF")

    // MARK: - Gradients
    static let primaryGradient = LinearGradient(
        colors: [primaryBlue, secondaryBlue],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let subtleTopGradient = LinearGradient(
        colors: [primaryBlue.opacity(0.18), Color.clear],
        startPoint: .top,
        endPoint: .bottom
    )

    // MARK: - Typography  (SF Pro, rounded, weight 400–600)
    static let titleFont   = Font.system(.title2,   design: .rounded).weight(.bold)
    static let headingFont = Font.system(.headline, design: .rounded).weight(.semibold)
    static let bodyFont    = Font.system(.body,     design: .rounded).weight(.regular)
    static let captionFont = Font.system(.caption,  design: .rounded).weight(.regular)

    // MARK: - Geometry
    static let cornerRadius:  CGFloat = 20
    static let innerRadius:   CGFloat = 14
    static let panelWidth:    CGFloat = 500
    static let chatWidth:     CGFloat = 460

    // MARK: - Surface helpers
    static func glassBackground(material: NSVisualEffectView.Material = .hudWindow) -> some View {
        ZStack {
            VisualEffectBlur(material: material, blendingMode: .behindWindow)
            subtleTopGradient
        }
    }

    static func glassStroke(radius: CGFloat = cornerRadius) -> some View {
        RoundedRectangle(cornerRadius: radius)
            .stroke(Color.white.opacity(0.15), lineWidth: 1)
    }
}
