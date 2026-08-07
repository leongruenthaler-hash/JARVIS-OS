import SwiftUI

struct JarvisFuturisticBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(red: 0.005, green: 0.010, blue: 0.026),
                    Color(red: 0.010, green: 0.030, blue: 0.070),
                    Color(red: 0.000, green: 0.006, blue: 0.016)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            RadialGradient(
                colors: [
                    Color.blue.opacity(0.24),
                    Color.cyan.opacity(0.08),
                    .clear
                ],
                center: .topTrailing,
                startRadius: 40,
                endRadius: 640
            )

            RadialGradient(
                colors: [
                    Color.cyan.opacity(0.14),
                    .clear
                ],
                center: .bottomLeading,
                startRadius: 20,
                endRadius: 520
            )

            JarvisHUDGrid()
                .opacity(0.18)
        }
        .ignoresSafeArea()
    }
}

private struct JarvisHUDGrid: View {
    var body: some View {
        Canvas { context, size in
            let spacing: CGFloat = 72
            var path = Path()
            var x: CGFloat = 0
            while x <= size.width {
                path.move(to: CGPoint(x: x, y: 0))
                path.addLine(to: CGPoint(x: x, y: size.height))
                x += spacing
            }
            var y: CGFloat = 0
            while y <= size.height {
                path.move(to: CGPoint(x: 0, y: y))
                path.addLine(to: CGPoint(x: size.width, y: y))
                y += spacing
            }
            context.stroke(path, with: .color(Color.cyan.opacity(0.20)), lineWidth: 0.5)
        }
        .allowsHitTesting(false)
    }
}

struct JarvisGlowOrb: View {
    let state: JarvisVoiceState
    var size: CGFloat = 220
    @State private var pulse = false

    var body: some View {
        ZStack {
            Circle()
                .fill(Color.blue.opacity(0.14))
                .frame(width: size, height: size)
                .blur(radius: 28)
                .scaleEffect(pulse ? glowScale : 0.94)

            Circle()
                .stroke(Color.cyan.opacity(0.38), lineWidth: 1)
                .frame(width: size * 0.86, height: size * 0.86)
                .scaleEffect(pulse ? ringScale : 0.92)

            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            Color.white.opacity(0.90),
                            Color.cyan.opacity(0.82),
                            Color.blue.opacity(0.52),
                            Color.black.opacity(0.12)
                        ],
                        center: .center,
                        startRadius: 2,
                        endRadius: size * 0.32
                    )
                )
                .frame(width: size * 0.48, height: size * 0.48)
                .shadow(color: Color.cyan.opacity(0.62), radius: 28, x: 0, y: 0)

            Image(systemName: state.symbol)
                .font(.system(size: size * 0.13, weight: .semibold))
                .foregroundStyle(.white)
        }
        .onAppear { pulse = true }
        .animation(.easeInOut(duration: animationDuration).repeatForever(autoreverses: true), value: pulse)
    }

    private var animationDuration: Double {
        switch state {
        case .idle: return 2.4
        case .listening, .preparingMicrophone, .alwaysListenStandby: return 1.0
        case .userSpeaking, .jarvisSpeaking: return 0.55
        case .thinking, .liveTranscribing, .transcribing, .wakeWordChecking: return 1.4
        case .error: return 0.7
        }
    }

    private var glowScale: CGFloat {
        switch state {
        case .idle: return 1.00
        case .listening, .preparingMicrophone, .alwaysListenStandby: return 1.06
        case .userSpeaking, .jarvisSpeaking: return 1.13
        case .thinking, .liveTranscribing, .transcribing, .wakeWordChecking: return 1.08
        case .error: return 1.04
        }
    }

    private var ringScale: CGFloat {
        switch state {
        case .idle: return 0.98
        case .listening, .preparingMicrophone, .alwaysListenStandby: return 1.04
        case .userSpeaking, .jarvisSpeaking: return 1.10
        case .thinking, .liveTranscribing, .transcribing, .wakeWordChecking: return 1.08
        case .error: return 1.02
        }
    }
}

struct JarvisGlassCard<Content: View>: View {
    var tint: Color = .cyan
    var cornerRadius: CGFloat = 22
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(18)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(Color(red: 0.01, green: 0.035, blue: 0.075).opacity(0.34))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(
                            colors: [tint.opacity(0.58), Color.cyan.opacity(0.18), Color.white.opacity(0.08)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            )
            .shadow(color: tint.opacity(0.18), radius: 24, x: 0, y: 10)
    }
}

struct JarvisHUDButton: ButtonStyle {
    var tint: Color = .cyan

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(Color.black.opacity(configuration.isPressed ? 0.34 : 0.20), in: Capsule())
            .overlay(Capsule().strokeBorder(tint.opacity(configuration.isPressed ? 0.75 : 0.42), lineWidth: 1))
            .shadow(color: tint.opacity(configuration.isPressed ? 0.24 : 0.12), radius: configuration.isPressed ? 14 : 8)
            .foregroundStyle(.white)
    }
}

struct JarvisStatusPill: View {
    let title: String
    let symbol: String
    var tint: Color = .cyan

    var body: some View {
        Label(title, systemImage: symbol)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.white.opacity(0.92))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.black.opacity(0.22), in: Capsule())
            .overlay(Capsule().strokeBorder(tint.opacity(0.42), lineWidth: 1))
            .shadow(color: tint.opacity(0.12), radius: 8)
    }
}

/// Shared color mapping for memory facts (Gedaechtnis-Kern-Ansicht) - used by both
/// MemoryCoreView's nodes and MemoryView's list pills, so the two representations of
/// the same fact never disagree on what a color means. See
/// plans/2026-08-07-jarvis-memory-neural-network-view.md.
func memorySensitivityColor(_ sensitivity: String) -> Color {
    switch sensitivity {
    case "personal": return .orange
    case "confidential", "highly-sensitive": return .red
    default: return .cyan
    }
}

func memoryStatusOpacity(_ status: String) -> Double {
    switch status {
    case "pending_confirmation": return 0.55
    case "rejected": return 0.25
    default: return 0.9
    }
}

struct JarvisDividerLine: View {
    var tint: Color = .cyan

    var body: some View {
        Rectangle()
            .fill(
                LinearGradient(
                    colors: [.clear, tint.opacity(0.44), .clear],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .frame(height: 1)
    }
}
