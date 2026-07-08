import SwiftUI

struct LiquidGlassBackground: View {
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        Group {
            if theme == .futuristicBlue {
                JarvisFuturisticBackground()
            } else {
                ZStack {
                    LinearGradient(
                        colors: [
                            Color(nsColor: .windowBackgroundColor),
                            Color.cyan.opacity(0.10),
                            Color.indigo.opacity(0.08),
                            Color(nsColor: .textBackgroundColor).opacity(0.42)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    Rectangle()
                        .fill(.ultraThinMaterial)
                        .opacity(0.34)
                }
                .ignoresSafeArea()
            }
        }
    }
}

struct LiquidGlassIcon: View {
    let symbol: String
    var tint: Color = .cyan
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        let activeTint = theme.isFuturistic ? theme.primaryAccent : tint

        Image(systemName: symbol)
            .font(.system(size: 28, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 62, height: 62)
            .background(
                LinearGradient(
                    colors: theme.isFuturistic
                        ? [activeTint.opacity(0.95), theme.secondaryAccent.opacity(0.75), .blue.opacity(0.55)]
                        : [tint, .blue, .indigo],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                in: RoundedRectangle(cornerRadius: 22, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(activeTint.opacity(theme.isFuturistic ? 0.42 : 0.0), lineWidth: 1)
            )
            .shadow(color: activeTint.opacity(theme.isFuturistic ? 0.34 : 0.22), radius: theme.isFuturistic ? 24 : 18, x: 0, y: 10)
    }
}

extension View {
    func liquidGlassPanel(tint: Color = .cyan, cornerRadius: CGFloat = 26) -> some View {
        modifier(JarvisGlassPanelModifier(tint: tint, cornerRadius: cornerRadius, padding: 18))
    }

    func liquidGlassCard(tint: Color = .cyan, cornerRadius: CGFloat = 22) -> some View {
        modifier(JarvisGlassPanelModifier(tint: tint, cornerRadius: cornerRadius, padding: 0))
    }
}

private struct JarvisGlassPanelModifier: ViewModifier {
    @Environment(\.jarvisTheme) private var theme
    let tint: Color
    let cornerRadius: CGFloat
    let padding: CGFloat

    func body(content: Content) -> some View {
        let activeTint = theme.isFuturistic ? theme.primaryAccent : tint

        content
            .padding(padding)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(theme.isFuturistic ? Color(red: 0.01, green: 0.035, blue: 0.075).opacity(0.30) : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(borderGradient(activeTint), lineWidth: 1)
            )
            .shadow(color: activeTint.opacity(theme.isFuturistic ? 0.18 : 0.10), radius: theme.isFuturistic ? 28 : 24, x: 0, y: 12)
            .shadow(color: Color.black.opacity(theme.isFuturistic ? 0.18 : 0.07), radius: 10, x: 0, y: 4)
    }

    private func borderGradient(_ activeTint: Color) -> LinearGradient {
        LinearGradient(
            colors: theme.isFuturistic
                ? [
                    activeTint.opacity(0.52),
                    theme.secondaryAccent.opacity(0.20),
                    Color.white.opacity(0.06)
                ]
                : [
                    Color.white.opacity(0.34),
                    tint.opacity(0.22),
                    Color.white.opacity(0.08)
                ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}
