import SwiftUI

enum JarvisTheme: String, CaseIterable, Identifiable {
    case classic
    case futuristicBlue
    /// Warm dark glassmorphism look used ONLY as an environment override inside `DashboardView`
    /// so its 13 embedded feature views recolor to match the Dashboard's own visual language.
    /// It is intentionally NOT offered in Settings' theme picker (see `SettingsView`) - it is
    /// not a user-selectable classic-shell theme, it is driven purely by `DashboardView`.
    case dashboard

    var id: String { rawValue }

    var title: String {
        switch self {
        case .classic:
            return "Aktuelles Design"
        case .futuristicBlue:
            return "Futuristic Blue"
        case .dashboard:
            return "Dashboard"
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
        }
    }

    /// True ONLY for `.futuristicBlue`. Genuinely futuristic-specific branches (the blue
    /// `JarvisFuturisticBackground`, the `JarvisGlowOrb`, hardcoded blue fills) must keep
    /// keying off this so `.dashboard` never masquerades as futuristic.
    var isFuturistic: Bool { self == .futuristicBlue }

    /// True for `.dashboard` only.
    var isDashboard: Bool { self == .dashboard }

    /// "Is this a dark glass theme?" - true for both `.futuristicBlue` and `.dashboard`.
    /// Use this (rather than `isFuturistic`) for the generic dark-vs-light glass decisions
    /// that pull their colors from `primaryAccent`/`secondaryAccent`, so `.dashboard`
    /// automatically renders with its own orange accents instead of the classic light look.
    var isDark: Bool { self != .classic }

    var primaryAccent: Color {
        switch self {
        case .classic: return .cyan
        case .futuristicBlue: return Color(red: 0.16, green: 0.58, blue: 1.0)
        // DashboardPalette.accent
        case .dashboard: return Color(red: 0.910, green: 0.475, blue: 0.165)
        }
    }

    var secondaryAccent: Color {
        switch self {
        case .classic: return .indigo
        case .futuristicBlue: return Color(red: 0.32, green: 0.92, blue: 1.0)
        // DashboardPalette.accentLight
        case .dashboard: return Color(red: 0.961, green: 0.627, blue: 0.333)
        }
    }

    var backgroundTop: Color {
        switch self {
        case .classic: return Color(nsColor: .windowBackgroundColor)
        case .futuristicBlue: return Color(red: 0.01, green: 0.025, blue: 0.055)
        // DashboardPalette.background (warm near-black)
        case .dashboard: return Color(red: 0.05, green: 0.035, blue: 0.03)
        }
    }

    var backgroundBottom: Color {
        switch self {
        case .classic: return Color(nsColor: .textBackgroundColor).opacity(0.42)
        case .futuristicBlue: return Color(red: 0.005, green: 0.008, blue: 0.018)
        // A touch darker than DashboardPalette.background, keeping the same warm hue.
        case .dashboard: return Color(red: 0.03, green: 0.02, blue: 0.017)
        }
    }

    var cardFillOpacity: Double {
        switch self {
        case .classic: return 1.0
        case .futuristicBlue: return 0.30
        // Matches dashboardGlass' cardFill (Color.black.opacity(0.10)).
        case .dashboard: return 0.10
        }
    }

    var borderOpacity: Double {
        switch self {
        case .classic: return 0.18
        case .futuristicBlue: return 0.42
        // Matches dashboardGlass' white border stroke (opacity 0.10).
        case .dashboard: return 0.10
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
