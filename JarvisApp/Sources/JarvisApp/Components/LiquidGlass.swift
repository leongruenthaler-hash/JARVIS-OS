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
            case .signal:
                // Nahezu schwarz mit einem dezenten radialen Mint-Gluehen hinter dem
                // Inhalt, wie im Signal-Mockup - kein flaechiger Farbverlauf, das
                // Schwarz soll dominieren.
                ZStack {
                    LinearGradient(
                        colors: [theme.backgroundTop, theme.backgroundBottom],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    RadialGradient(
                        colors: [theme.primaryAccent.opacity(0.10), .clear],
                        center: .topLeading,
                        startRadius: 40,
                        endRadius: 520
                    )
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
        case .signal:
            gradientColors = [activeTint.opacity(0.95), theme.secondaryAccent.opacity(0.65), activeTint.opacity(0.45)]
        case .classic:
            gradientColors = [tint, .blue, .indigo]
        }

        // Signal ist bewusst kantiger/flacher als die anderen Themes (Mockup-Vorgabe:
        // scharfe Kanten statt weicher Iron-Man-Glow-Blobs) - kleinerer Radius, duennerer
        // Verlauf, schaerferer statt weicher Schatten.
        let radius: CGFloat = theme.isSignal ? 12 : 22
        let shadowRadius: CGFloat = theme.isSignal ? 10 : (theme.isDark ? 24 : 18)

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
                in: RoundedRectangle(cornerRadius: radius, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(activeTint.opacity(theme.isDark ? 0.42 : 0.0), lineWidth: 1)
            )
            .shadow(color: activeTint.opacity(theme.isDark ? 0.34 : 0.22), radius: shadowRadius, x: 0, y: theme.isSignal ? 6 : 10)
    }
}

extension View {
    func liquidGlassPanel(tint: Color = .cyan, cornerRadius: CGFloat = 26) -> some View {
        modifier(JarvisGlassPanelModifier(tint: tint, cornerRadius: cornerRadius, padding: 18))
    }

    func liquidGlassCard(tint: Color = .cyan, cornerRadius: CGFloat = 22) -> some View {
        modifier(JarvisGlassPanelModifier(tint: tint, cornerRadius: cornerRadius, padding: 0))
    }

    /// Kapsel-Variante fuer Chips/Toolbar-Pillen (Eingabeleisten, Filter-Buttons), die
    /// bisher an vielen Stellen rohes `.thinMaterial`/`.ultraThinMaterial` in einer
    /// `Capsule()` nutzten und dadurch die Signal-Kartenform (siehe JarvisGlassPanelModifier)
    /// nicht mitbekamen. Gleiches Prinzip, nur Capsule statt RoundedRectangle.
    func liquidGlassCapsule(tint: Color = .cyan) -> some View {
        modifier(JarvisGlassCapsuleModifier(tint: tint))
    }
}

private struct JarvisGlassCapsuleModifier: ViewModifier {
    @Environment(\.jarvisTheme) private var theme
    let tint: Color

    func body(content: Content) -> some View {
        let activeTint = theme.isDark ? theme.primaryAccent : tint

        if theme.isSignal {
            return AnyView(
                content
                    .background(Capsule().fill(Color.white.opacity(0.045)))
                    .overlay(Capsule().strokeBorder(activeTint.opacity(0.30), lineWidth: 1))
            )
        }
        return AnyView(
            content
                .background(.thinMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(activeTint.opacity(theme.isDark ? 0.30 : 0.14), lineWidth: 1))
        )
    }
}

private struct JarvisGlassPanelModifier: ViewModifier {
    @Environment(\.jarvisTheme) private var theme
    let tint: Color
    let cornerRadius: CGFloat
    let padding: CGFloat

    func body(content: Content) -> some View {
        let activeTint = theme.isDark ? theme.primaryAccent : tint

        // Signal ist die einzige Ausnahme, die NIE die schwere Weichzeichner-Blur-Karte
        // der anderen Themes bekommt - das war der eigentliche Grund, warum das bisherige
        // "Signal"-Redesign trotz korrekter Akzentfarbe wie das alte Liquid-Glass-Design
        // aussah (siehe Plan "Signal-Look wirklich komplett umsetzen", 2026-08-22): nur
        // Fuellfarbe/Rand waren angepasst, die Form (dicker Blur, grosse runde Ecken) war
        // ueberall identisch. Flache Fuellung + duenner Rand + kleinerer, von der
        // Aufrufstelle unabhaengiger Radius statt Material-Blur.
        if theme.isSignal {
            let radius = min(cornerRadius, 14)
            return AnyView(
                content
                    .padding(padding)
                    .background(
                        RoundedRectangle(cornerRadius: radius, style: .continuous)
                            .fill(Color.white.opacity(cardFillOpacityForSignal))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: radius, style: .continuous)
                            .strokeBorder(activeTint.opacity(0.32), lineWidth: 1)
                    )
                    .shadow(color: activeTint.opacity(0.10), radius: 12, x: 0, y: 4)
            )
        }

        let underlayFill: Color
        switch theme {
        case .futuristicBlue:
            underlayFill = Color(red: 0.01, green: 0.035, blue: 0.075).opacity(0.30)
        case .dashboard:
            // Matches dashboardGlass' cardFill (Color.black.opacity(0.10)) over the material.
            underlayFill = Color.black.opacity(0.10)
        case .signal:
            underlayFill = .clear // unreachable, handled above
        case .classic:
            underlayFill = Color.clear
        }

        return AnyView(
            content
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
        )
    }

    /// theme.cardFillOpacity ist fuer signal auf 0.04 gestimmt (dunkler Grundton) - hier
    /// als heller weisser Overlay auf dem fast-schwarzen Hintergrund gebraucht, deshalb
    /// eigene, etwas hoehere Konstante statt der theme-Property direkt.
    private var cardFillOpacityForSignal: Double { 0.045 }

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
