import SwiftUI

// MARK: - Ring state enum

enum ShailRingState: Equatable {
    case idle
    case listening
    case listeningAndSeeing   // mic on + screen capture active
    case thinking             // LLM planning
    case executing            // running a task/tool

    var label: String {
        switch self {
        case .idle:               return "Ready"
        case .listening:          return "Listening…"
        case .listeningAndSeeing: return "Listening + Seeing"
        case .thinking:           return "Thinking…"
        case .executing:          return "Executing…"
        }
    }

    var accentColor: Color {
        switch self {
        case .idle:               return .white.opacity(0.3)
        case .listening:          return ShailTheme.primaryBlue
        case .listeningAndSeeing: return ShailTheme.primaryBlue
        case .thinking:           return ShailTheme.primaryBlue
        case .executing:          return ShailTheme.secondaryBlue
        }
    }

    var centerSymbol: String {
        switch self {
        case .idle:               return "bolt.fill"
        case .listening:          return "mic.fill"
        case .listeningAndSeeing: return "eyes"
        case .thinking:           return "brain.head.profile"
        case .executing:          return "gearshape.fill"
        }
    }
}

// MARK: - Ring view

struct ShailStatusRing: View {
    let state: ShailRingState

    @State private var pulseScale:   CGFloat = 1.0
    @State private var spinDegrees:  Double  = 0
    @State private var glowOpacity:  Double  = 0.4

    private let size:        CGFloat = 76
    private let strokeWidth: CGFloat = 3

    var body: some View {
        ZStack {
            // Ambient glow halo for active states
            if state != .idle {
                Circle()
                    .fill(state.accentColor.opacity(0.10))
                    .frame(width: size + 22, height: size + 22)
                    .opacity(glowOpacity)
            }

            // Base dim ring (always present)
            Circle()
                .stroke(Color.white.opacity(0.18), lineWidth: strokeWidth)
                .frame(width: size, height: size)

            // State-specific ring layer
            stateLayer

            // Centre icon
            Image(systemName: state.centerSymbol)
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(
                    state == .idle
                        ? AnyShapeStyle(Color.white.opacity(0.55))
                        : AnyShapeStyle(ShailTheme.primaryGradient)
                )
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.72), value: state)
        .onAppear   { animate() }
        .onChange(of: state) { _, _ in animate() }
    }

    // MARK: - State layers

    @ViewBuilder
    private var stateLayer: some View {
        switch state {

        case .idle:
            EmptyView()

        case .listening:
            // Solid glowing ring
            Circle()
                .stroke(ShailTheme.primaryBlue, lineWidth: strokeWidth)
                .frame(width: size, height: size)
                .shadow(color: ShailTheme.primaryBlue.opacity(0.8), radius: 8)

        case .listeningAndSeeing:
            // Filled radial glow + solid ring
            Circle()
                .fill(RadialGradient(
                    colors: [ShailTheme.primaryBlue.opacity(0.30), .clear],
                    center: .center,
                    startRadius: 0,
                    endRadius: size / 2
                ))
                .frame(width: size, height: size)
            Circle()
                .stroke(ShailTheme.primaryBlue, lineWidth: strokeWidth)
                .frame(width: size, height: size)
                .shadow(color: ShailTheme.primaryBlue.opacity(0.9), radius: 14)

        case .thinking:
            // Pulsing ring
            Circle()
                .stroke(ShailTheme.primaryBlue, lineWidth: strokeWidth)
                .frame(width: size, height: size)
                .scaleEffect(pulseScale)
                .opacity(2.1 - pulseScale)
                .shadow(color: ShailTheme.primaryBlue.opacity(0.6), radius: 10)

        case .executing:
            // Spinning arc
            SpinArc()
                .stroke(
                    ShailTheme.primaryGradient,
                    style: StrokeStyle(lineWidth: strokeWidth + 1, lineCap: .round)
                )
                .frame(width: size, height: size)
                .rotationEffect(.degrees(spinDegrees))
        }
    }

    // MARK: - Animation triggers

    private func animate() {
        pulseScale  = 1.0
        spinDegrees = 0
        glowOpacity = 0.4

        switch state {
        case .thinking:
            withAnimation(.easeInOut(duration: 0.85).repeatForever(autoreverses: true)) {
                pulseScale = 1.20
            }
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                glowOpacity = 1.0
            }

        case .executing:
            withAnimation(.linear(duration: 1.05).repeatForever(autoreverses: false)) {
                spinDegrees = 360
            }
            withAnimation(.easeInOut(duration: 0.55).repeatForever(autoreverses: true)) {
                glowOpacity = 1.0
            }

        case .listening, .listeningAndSeeing:
            withAnimation(.easeInOut(duration: 1.3).repeatForever(autoreverses: true)) {
                glowOpacity = 1.0
            }

        case .idle:
            break
        }
    }
}

// MARK: - Spinning arc shape (270° open arc)

private struct SpinArc: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.addArc(
            center:     CGPoint(x: rect.midX, y: rect.midY),
            radius:     rect.width / 2,
            startAngle: .degrees(-90),
            endAngle:   .degrees(180),
            clockwise:  false
        )
        return p
    }
}
