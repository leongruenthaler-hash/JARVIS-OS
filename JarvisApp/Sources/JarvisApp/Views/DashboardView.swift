import SwiftUI

/// "Jarvis OS Dashboard" - a completely separate, additive UI theme (sidebar nav + card
/// grid, warm glassmorphism look) alongside the existing MainShellView. Deliberately its
/// OWN view tree, not a recolor of MainShellView via `JarvisTheme` - see DashboardPalette
/// below, which is a fixed palette independent of the classic/futuristicBlue color themes.
///
/// Etappe 2 (this file): empty Grundgerüst only - layout, colors, card frames, no data
/// content. Etappe 3 fills the four already-verified data sources (SystemMonitor,
/// WeatherService, NowPlayingService, ProductivityTracker) into the matching cards.
struct DashboardView: View {
    @EnvironmentObject private var appState: AppState
    @State private var activeSection: DashboardSection = .overview

    var body: some View {
        HStack(spacing: 0) {
            sidebar
                .frame(width: 240)

            VStack(spacing: 0) {
                header
                    .padding(.horizontal, 32)
                    .padding(.top, 24)
                    .padding(.bottom, 16)

                if activeSection == .overview {
                    ScrollView {
                        cardGrid
                            .padding(.horizontal, 32)
                            .padding(.bottom, 24)
                    }
                    quickAccessBar
                        .padding(.horizontal, 32)
                        .padding(.bottom, 20)
                } else {
                    placeholderSection
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DashboardBackground())
        .preferredColorScheme(.dark)
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(spacing: 0) {
            VStack(spacing: 4) {
                ZStack {
                    ForEach(0..<3) { ring in
                        Circle()
                            .stroke(DashboardPalette.accent.opacity(0.55 - Double(ring) * 0.15), lineWidth: 1.5)
                            .frame(width: 34 - CGFloat(ring) * 9, height: 34 - CGFloat(ring) * 9)
                    }
                    Circle()
                        .fill(DashboardPalette.accent)
                        .frame(width: 6, height: 6)
                }
                .frame(height: 40)

                Text("JARVIS")
                    .font(.system(size: 17, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                Text("OS")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }
            .padding(.top, 28)
            .padding(.bottom, 26)

            VStack(alignment: .leading, spacing: 4) {
                ForEach(DashboardSection.allCases) { section in
                    sidebarRow(section)
                }
            }
            .padding(.horizontal, 14)

            Spacer(minLength: 12)

            ZStack {
                Circle()
                    .fill(DashboardPalette.accent.opacity(0.18))
                    .frame(width: 78, height: 78)
                    .blur(radius: 8)
                Circle()
                    .strokeBorder(DashboardPalette.accent.opacity(0.7), lineWidth: 1.5)
                    .frame(width: 58, height: 58)
                Image(systemName: "waveform")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(DashboardPalette.accent)
            }
            .padding(.bottom, 18)

            statusCard
                .padding(.horizontal, 14)
                .padding(.bottom, 20)
        }
        .frame(maxHeight: .infinity)
        .background(DashboardPalette.sidebarFill)
    }

    private func sidebarRow(_ section: DashboardSection) -> some View {
        let isActive = section == activeSection
        return Button {
            activeSection = section
        } label: {
            HStack(spacing: 10) {
                Image(systemName: section.symbol)
                    .font(.system(size: 13, weight: .medium))
                    .frame(width: 18)
                Text(section.title)
                    .font(.system(size: 13, weight: .medium))
                Spacer(minLength: 0)
            }
            .foregroundStyle(isActive ? DashboardPalette.accent : DashboardPalette.textSecondary)
            .padding(.vertical, 9)
            .padding(.horizontal, 10)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(isActive ? DashboardPalette.accent.opacity(0.14) : .clear)
            )
            .overlay(alignment: .leading) {
                if isActive {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(DashboardPalette.accent)
                        .frame(width: 3)
                        .padding(.vertical, 6)
                }
            }
        }
        .buttonStyle(.plain)
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text("Jarvis Online")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                Circle()
                    .fill(DashboardPalette.accent)
                    .frame(width: 6, height: 6)
            }
            Text("Alle Systeme aktiv")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(DashboardPalette.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .dashboardGlass(cornerRadius: 14)
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .center, spacing: 24) {
            VStack(alignment: .leading, spacing: 3) {
                Text(greetingAttributed)
                    .font(.system(size: 29, weight: .bold, design: .rounded))
                Text("Hier ist dein Überblick für heute.")
                    .font(.system(size: 13))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }

            Spacer(minLength: 12)

            HStack(spacing: 10) {
                Circle()
                    .fill(
                        LinearGradient(colors: [.blue, .purple, .pink], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .frame(width: 20, height: 20)
                Text("Frag Jarvis oder suche ...")
                    .font(.system(size: 13))
                    .foregroundStyle(DashboardPalette.textSecondary)
                Spacer(minLength: 0)
                Image(systemName: "mic.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .frame(maxWidth: 420)
            .background(Capsule().fill(Color.black.opacity(0.32)))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.10), lineWidth: 1))

            Spacer(minLength: 12)

            HStack(spacing: 12) {
                VStack(alignment: .trailing, spacing: 2) {
                    Text(currentTimeString)
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(.white)
                    Text(currentDateString)
                        .font(.system(size: 11))
                        .foregroundStyle(DashboardPalette.textSecondary)
                }
                ZStack(alignment: .bottomTrailing) {
                    Circle()
                        .fill(Color.white.opacity(0.12))
                        .frame(width: 36, height: 36)
                        .overlay(
                            Image(systemName: "person.fill")
                                .font(.system(size: 14))
                                .foregroundStyle(.white.opacity(0.8))
                        )
                    Circle()
                        .fill(Color.green)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().strokeBorder(DashboardPalette.background, lineWidth: 1.5))
                }
            }
        }
    }

    private var greetedName: String {
        appState.userName.isEmpty ? "Leon" : appState.userName
    }

    private var greetingAttributed: AttributedString {
        var text = AttributedString("Guten Tag, \(greetedName).")
        text.foregroundColor = .white
        if let range = text.range(of: greetedName) {
            text[range].foregroundColor = DashboardPalette.accent
        }
        return text
    }

    private var currentTimeString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date())
    }

    private var currentDateString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, d. MMMM"
        formatter.locale = Locale(identifier: "de_DE")
        return formatter.string(from: Date())
    }

    // MARK: - Card grid (Grundgerüst only - empty bodies, filled in Etappe 3)

    private var cardGrid: some View {
        VStack(spacing: 16) {
            HStack(spacing: 16) {
                DashboardCard(title: "Kalender", symbol: "calendar")
                DashboardCard(title: "Mail", symbol: "envelope.fill")
                DashboardCard(title: "Wetter", symbol: "cloud.sun.fill")
                DashboardCard(title: "Batterie", symbol: "battery.100", titleTint: .green)
            }

            HStack(spacing: 16) {
                DashboardCard(title: "System-Auslastung", symbol: "cpu")
                DashboardCard(title: "Tagesstatistik", symbol: "chart.line.uptrend.xyaxis")
                DashboardCard(title: "Aufgaben", symbol: "checklist", trailingSymbol: "plus")
            }

            HStack(spacing: 16) {
                DashboardCard(title: "Musik", symbol: "music.note")
                    .frame(maxWidth: .infinity)
                    .layoutPriority(2)
                DashboardCard(title: "Schnellzugriff", symbol: "square.grid.2x2.fill")
                    .frame(maxWidth: .infinity)
                    .layoutPriority(1)
            }
        }
    }

    private var quickAccessBar: some View {
        HStack(spacing: 12) {
            Text("Schnellzugriff")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(DashboardPalette.textSecondary)

            ForEach(["Notizen erstellen", "Screenshot machen", "Erinnerung setzen", "Timer starten"], id: \.self) { label in
                Text(label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(Capsule().fill(Color.white.opacity(0.08)))
                    .overlay(Capsule().strokeBorder(Color.white.opacity(0.10), lineWidth: 1))
            }

            Spacer(minLength: 0)

            HStack(spacing: 14) {
                Image(systemName: "sun.max")
                Image(systemName: "speaker.wave.2")
                Image(systemName: "wifi")
            }
            .font(.system(size: 13))
            .foregroundStyle(DashboardPalette.textSecondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .dashboardGlass(cornerRadius: 16)
    }

    private var placeholderSection: some View {
        VStack(spacing: 10) {
            Image(systemName: activeSection.symbol)
                .font(.system(size: 30))
                .foregroundStyle(DashboardPalette.textSecondary)
            Text("\(activeSection.title) kommt in einer späteren Etappe.")
                .font(.system(size: 14))
                .foregroundStyle(DashboardPalette.textSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Reusable card shell

private struct DashboardCard: View {
    let title: String
    let symbol: String
    var titleTint: Color = DashboardPalette.accent
    var trailingSymbol: String = "ellipsis"

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                HStack(spacing: 8) {
                    Image(systemName: symbol)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(titleTint)
                    Text(title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.white)
                }
                Spacer(minLength: 0)
                Image(systemName: trailingSymbol)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }

            Text("Noch keine Daten in diesem Grundgerüst.")
                .font(.system(size: 12))
                .foregroundStyle(DashboardPalette.textSecondary.opacity(0.7))
                .frame(maxWidth: .infinity, minHeight: 64, alignment: .center)
                .multilineTextAlignment(.center)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .dashboardGlass(cornerRadius: 20)
    }
}

// MARK: - Sections (Dashboard-specific, distinct from JarvisSection)

private enum DashboardSection: String, CaseIterable, Identifiable {
    case overview, chat, files, calendar, tasks, agents, automations, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: "Übersicht"
        case .chat: "Chat"
        case .files: "Dateien"
        case .calendar: "Kalender"
        case .tasks: "Aufgaben"
        case .agents: "Agenten"
        case .automations: "Automatisierungen"
        case .settings: "Einstellungen"
        }
    }

    var symbol: String {
        switch self {
        case .overview: "house.fill"
        case .chat: "bubble.left.and.bubble.right.fill"
        case .files: "folder.fill"
        case .calendar: "calendar"
        case .tasks: "checklist"
        case .agents: "gearshape.2.fill"
        case .automations: "point.3.connected.trianglepath.dotted"
        case .settings: "gearshape.fill"
        }
    }
}

// MARK: - Palette, background and glass style

enum DashboardPalette {
    static let accent = Color(red: 0.910, green: 0.475, blue: 0.165)
    static let accentLight = Color(red: 0.961, green: 0.627, blue: 0.333)
    static let background = Color(red: 0.05, green: 0.035, blue: 0.03)
    static let textSecondary = Color(red: 0.612, green: 0.639, blue: 0.686)
    static let sidebarFill = Color.black.opacity(0.28)
    static let cardFill = Color.black.opacity(0.46)
}

struct DashboardBackground: View {
    var body: some View {
        ZStack {
            DashboardPalette.background

            RadialGradient(
                colors: [DashboardPalette.accent.opacity(0.22), .clear],
                center: .topLeading,
                startRadius: 40,
                endRadius: 620
            )
            RadialGradient(
                colors: [DashboardPalette.accentLight.opacity(0.14), .clear],
                center: .bottomTrailing,
                startRadius: 60,
                endRadius: 700
            )

            VStack {
                LinearGradient(
                    colors: [DashboardPalette.accent.opacity(0.65), .clear],
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .frame(height: 2)
                .blur(radius: 1)
                Spacer()
            }

            Color.black.opacity(0.18)
        }
        .ignoresSafeArea()
    }
}

private extension View {
    func dashboardGlass(cornerRadius: CGFloat) -> some View {
        self
            .background(
                ZStack {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .fill(.ultraThinMaterial)
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .fill(DashboardPalette.cardFill)
                }
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.10), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.35), radius: 14, x: 0, y: 8)
    }
}
