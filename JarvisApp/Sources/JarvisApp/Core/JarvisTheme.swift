import SwiftUI

enum JarvisTheme: String, CaseIterable, Identifiable {
    case classic
    case futuristicBlue

    var id: String { rawValue }

    var title: String {
        switch self {
        case .classic:
            return "Aktuelles Design"
        case .futuristicBlue:
            return "Futuristic Blue"
        }
    }

    var subtitle: String {
        switch self {
        case .classic:
            return "Das bisherige Liquid-Glass-Design."
        case .futuristicBlue:
            return "Dunkel, blau, ruhig und ein bisschen Kommandobruecke."
        }
    }

    var isFuturistic: Bool { self == .futuristicBlue }

    var primaryAccent: Color {
        switch self {
        case .classic: return .cyan
        case .futuristicBlue: return Color(red: 0.16, green: 0.58, blue: 1.0)
        }
    }

    var secondaryAccent: Color {
        switch self {
        case .classic: return .indigo
        case .futuristicBlue: return Color(red: 0.32, green: 0.92, blue: 1.0)
        }
    }

    var backgroundTop: Color {
        switch self {
        case .classic: return Color(nsColor: .windowBackgroundColor)
        case .futuristicBlue: return Color(red: 0.01, green: 0.025, blue: 0.055)
        }
    }

    var backgroundBottom: Color {
        switch self {
        case .classic: return Color(nsColor: .textBackgroundColor).opacity(0.42)
        case .futuristicBlue: return Color(red: 0.005, green: 0.008, blue: 0.018)
        }
    }

    var cardFillOpacity: Double {
        switch self {
        case .classic: return 1.0
        case .futuristicBlue: return 0.30
        }
    }

    var borderOpacity: Double {
        switch self {
        case .classic: return 0.18
        case .futuristicBlue: return 0.42
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
