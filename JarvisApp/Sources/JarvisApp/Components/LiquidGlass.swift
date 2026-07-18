import SwiftUI

struct LiquidGlassBackground: View {
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        Group {
            switch theme {
            case .futuristicBlue:
                JarvisFuturisticBackground()
            case .dashboard:
                // Warm dark backdrop matching the Dashboard's own DashboardBackground base
                // tone, so embedded feature views read as the same dark glass surface.
                ZStack {
                    LinearGradient(
                        colors: [theme.backgroundTop, theme.backgroundBottom],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    theme.primaryAccent.opacity(0.06)
                        .blendMode(.screen)
                }
                .ignoresSafeArea()
            case .classic:
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
        let activeTint = theme.isDark ? theme.primaryAccent : tint

        let gradientColors: [Color]
        switch theme {
        case .futuristicBlue:
            gradientColors = [activeTint.opacity(0.95), theme.secondaryAccent.opacity(0.75), .blue.opacity(0.55)]
        case .dashboard:
            gradientColors = [activeTint.opacity(0.95), theme.secondaryAccent.opacity(0.75), theme.primaryAccent.opacity(0.55)]
        case .classic:
            gradientColors = [tint, .blue, .indigo]
        }

        return Image(systemName: symbol)
            .font(.system(size: 28, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 62, height: 62)
            .background(
                LinearGradient(
                    colors: gradientColors,
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                in: RoundedRectangle(cornerRadius: 22, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(activeTint.opacity(theme.isDark ? 0.42 : 0.0), lineWidth: 1)
            )
            .shadow(color: activeTint.opacity(theme.isDark ? 0.34 : 0.22), radius: theme.isDark ? 24 : 18, x: 0, y: 10)
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
        let activeTint = theme.isDark ? theme.primaryAccent : tint

        let underlayFill: Color
        switch theme {
        case .futuristicBlue:
            underlayFill = Color(red: 0.01, green: 0.035, blue: 0.075).opacity(0.30)
        case .dashboard:
            // Matches dashboardGlass' cardFill (Color.black.opacity(0.10)) over the material.
            underlayFill = Color.black.opacity(0.10)
        case .classic:
            underlayFill = Color.clear
        }

        return content
            .padding(padding)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(underlayFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(borderGradient(activeTint), lineWidth: 1)
            )
            .shadow(color: activeTint.opacity(theme.isDark ? 0.18 : 0.10), radius: theme.isDark ? 28 : 24, x: 0, y: 12)
            .shadow(color: Color.black.opacity(theme.isDark ? 0.18 : 0.07), radius: 10, x: 0, y: 4)
    }

    private func borderGradient(_ activeTint: Color) -> LinearGradient {
        LinearGradient(
            colors: theme.isDark
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
