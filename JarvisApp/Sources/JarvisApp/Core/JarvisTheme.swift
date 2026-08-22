import SwiftUI
import Foundation

/// Auswaehlbare Signal-Akzentfarbtoene (Leons Wunsch 2026-08-22, "ich möchte auch eine
/// komplette Farbpalette zur Auswahl haben") - dieselben 8 Farbtoene wie im Redesign-
/// Canvas-Mockup, gleiche Helligkeit/Saettigung (oklch), nur der Farbton unterscheidet sich.
enum SignalAccentHue: Double, CaseIterable, Identifiable {
    case mint = 165
    case cyan = 195
    case azure = 230
    case violet = 275
    case magenta = 320
    case coral = 20
    case amber = 65
    case lime = 128

    var id: Double { rawValue }

    var title: String {
        switch self {
        case .mint: return "Mint-Türkis"
        case .cyan: return "Zyan"
        case .azure: return "Azurblau"
        case .violet: return "Violett"
        case .magenta: return "Magenta"
        case .coral: return "Koralle"
        case .amber: return "Bernstein-Gold"
        case .lime: return "Lime-Grün"
        }
    }
}

/// Rechnet oklch(lightness chroma hue) in sRGB um (Bjorn Ottosson'sche Matrizen) - exakte
/// Umsetzung statt handgeschaetzter Hex-Werte, damit jeder Farbton in `SignalAccentHue`
/// (und potenziell jeder beliebige Winkel) korrekt berechnet wird.
enum OklchColor {
    static func color(lightness: Double, chroma: Double, hueDegrees: Double) -> Color {
        let hueRadians = hueDegrees * .pi / 180
        let a = chroma * cos(hueRadians)
        let b = chroma * sin(hueRadians)

        let l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
        let m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
        let s_ = lightness - 0.0894841775 * a - 1.2914855480 * b

        let l = l_ * l_ * l_
        let m = m_ * m_ * m_
        let s = s_ * s_ * s_

        let r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        let g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        let bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

        return Color(red: gammaEncode(r), green: gammaEncode(g), blue: gammaEncode(bl))
    }

    private static func gammaEncode(_ value: Double) -> Double {
        let clamped = min(max(value, 0), 1)
        return clamped <= 0.0031308 ? 12.92 * clamped : 1.055 * pow(clamped, 1 / 2.4) - 0.055
    }
}

enum JarvisTheme: String, CaseIterable, Identifiable {
    case classic
    case futuristicBlue
    /// Warm dark glassmorphism look used ONLY as an environment override inside `DashboardView`
    /// so its 13 embedded feature views recolor to match the Dashboard's own visual language.
    /// It is intentionally NOT offered in Settings' theme picker (see `SettingsView`) - it is
    /// not a user-selectable classic-shell theme, it is driven purely by `DashboardView`.
    case dashboard
    /// Leons gewaehltes System-Default-Theme (2026-08-22, aus vier Redesign-
    /// Explorationen ausgewaehlt): tiefschwarzer Hintergrund, ein einzelnes
    /// bioluminiszentes Mint-Tuerkis (oklch(0.78 0.13 165)) als Akzent. Anders
    /// als `.dashboard` bewusst NICHT aus dem Theme-Picker gefiltert - siehe
    /// SettingsView.
    case signal

    var id: String { rawValue }

    var title: String {
        switch self {
        case .classic:
            return "Aktuelles Design"
        case .futuristicBlue:
            return "Futuristic Blue"
        case .dashboard:
            return "Dashboard"
        case .signal:
            return "Signal"
        }
    }

    var subtitle: String {
        switch self {
        case .classic:
            return "Das bisherige Liquid-Glass-Design."
        case .futuristicBlue:
            return "Dunkel, blau, ruhig und ein bisschen Kommandobruecke."
        case .dashboard:
            return "Warm, dunkel, orange - das Glas-Design des Dashboards."
        case .signal:
            return "Tiefschwarz mit einem einzigen bioluminiszenten Mint-Signal."
        }
    }

    /// True ONLY for `.futuristicBlue`. Genuinely futuristic-specific branches (the blue
    /// `JarvisFuturisticBackground`, the `JarvisGlowOrb`, hardcoded blue fills) must keep
    /// keying off this so `.dashboard`/`.signal` never masquerade as futuristic.
    var isFuturistic: Bool { self == .futuristicBlue }

    /// True for `.dashboard` only.
    var isDashboard: Bool { self == .dashboard }

    /// True for `.signal` only.
    var isSignal: Bool { self == .signal }

    /// "Is this a dark glass theme?" - true for `.futuristicBlue`, `.dashboard` and `.signal`.
    /// Use this (rather than `isFuturistic`) for the generic dark-vs-light glass decisions
    /// that pull their colors from `primaryAccent`/`secondaryAccent`, so new dark themes
    /// automatically render with their own accents instead of the classic light look.
    var isDark: Bool { self != .classic }

    /// Vom Nutzer waehlbarer Signal-Farbton, siehe SettingsView. Direkter UserDefaults-
    /// Zugriff (nicht @AppStorage) - primaryAccent/secondaryAccent sind reine, ueberall
    /// aufrufbare computed properties auf einem plain enum, keine SwiftUI-View.
    static var signalAccentHueDegrees: Double {
        let stored = UserDefaults.standard.double(forKey: "JarvisSignalAccentHue")
        return stored == 0 ? SignalAccentHue.mint.rawValue : stored
    }

    var primaryAccent: Color {
        switch self {
        case .classic: return .cyan
        case .futuristicBlue: return Color(red: 0.16, green: 0.58, blue: 1.0)
        // DashboardPalette.accent
        case .dashboard: return Color(red: 0.910, green: 0.475, blue: 0.165)
        case .signal: return OklchColor.color(lightness: 0.78, chroma: 0.13, hueDegrees: Self.signalAccentHueDegrees)
        }
    }

    var secondaryAccent: Color {
        switch self {
        case .classic: return .indigo
        case .futuristicBlue: return Color(red: 0.32, green: 0.92, blue: 1.0)
        // DashboardPalette.accentLight
        case .dashboard: return Color(red: 0.961, green: 0.627, blue: 0.333)
        // Helleres Highlight desselben Farbtons.
        case .signal: return OklchColor.color(lightness: 0.90, chroma: 0.06, hueDegrees: Self.signalAccentHueDegrees)
        }
    }

    var backgroundTop: Color {
        switch self {
        case .classic: return Color(nsColor: .windowBackgroundColor)
        case .futuristicBlue: return Color(red: 0.01, green: 0.025, blue: 0.055)
        // DashboardPalette.background (warm near-black)
        case .dashboard: return Color(red: 0.05, green: 0.035, blue: 0.03)
        // #050506
        case .signal: return Color(red: 0.02, green: 0.02, blue: 0.024)
        }
    }

    var backgroundBottom: Color {
        switch self {
        case .classic: return Color(nsColor: .textBackgroundColor).opacity(0.42)
        case .futuristicBlue: return Color(red: 0.005, green: 0.008, blue: 0.018)
        // A touch darker than DashboardPalette.background, keeping the same warm hue.
        case .dashboard: return Color(red: 0.03, green: 0.02, blue: 0.017)
        // #030304
        case .signal: return Color(red: 0.012, green: 0.012, blue: 0.016)
        }
    }

    var cardFillOpacity: Double {
        switch self {
        case .classic: return 1.0
        case .futuristicBlue: return 0.30
        // Matches dashboardGlass' cardFill (Color.black.opacity(0.10)).
        case .dashboard: return 0.10
        // Flache Hairline-Border-Karten statt starkem Glas-Blur, siehe Mockup.
        case .signal: return 0.04
        }
    }

    var borderOpacity: Double {
        switch self {
        case .classic: return 0.18
        case .futuristicBlue: return 0.42
        // Matches dashboardGlass' white border stroke (opacity 0.10).
        case .dashboard: return 0.10
        case .signal: return 0.14
        }
    }
}

private struct JarvisThemeEnvironmentKey: EnvironmentKey {
    static let defaultValue: JarvisTheme = .classic
}

extension EnvironmentValues {
    var jarvisTheme: JarvisTheme {
        get { self[JarvisThemeEnvironmentKey.self] }
        set { self[JarvisThemeEnvironmentKey.self] = newValue }
    }
}
