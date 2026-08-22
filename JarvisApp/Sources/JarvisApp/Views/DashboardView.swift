import AppKit
import SwiftUI

/// "Jarvis OS Dashboard" - a completely separate, additive UI theme (sidebar nav + card
/// grid, warm glassmorphism look) alongside the existing MainShellView. Deliberately its
/// OWN view tree, not a recolor of MainShellView via `JarvisTheme` - see DashboardPalette
/// below, which is a fixed palette independent of the classic/futuristicBlue color themes.
///
/// Etappe 3 (this file): SystemMonitor, WeatherService and ProductivityTracker are wired
/// into their matching cards. Musik goes through the local server's AppleScript-based
/// music_client.py (like Kalender/Mail/Aufgaben) rather than an in-process Swift service -
/// the original in-process NowPlayingService (private MediaRemote API) was removed after
/// mediaremoted was confirmed to reject it for any third-party process, see project memory
/// "dashboard now-playing private-api blocked".
struct DashboardView: View {
    @EnvironmentObject private var appState: AppState
    @State private var activeSection: DashboardSection = .overview
    /// Measured width of the card grid (row 1's equally-flexed cards set this), reused to
    /// compute the unequal proportional splits in row 2 and row 3 - matches the reference
    /// design where row 2's third card and row 3's icon grid are narrower than their
    /// siblings, not an even 1/n split.
    @State private var gridContentWidth: CGFloat = 0

    @State private var systemStats: SystemStats?
    @State private var weatherSnapshot: WeatherSnapshot?
    /// Set when `pollWeather()`'s fetch throws, so WeatherCardContent can show a distinct
    /// error state instead of getting stuck on its loading spinner forever (see below -
    /// the old code discarded the error via `try?` with no fallback state).
    @State private var weatherFetchFailed = false

    var body: some View {
        HStack(spacing: 0) {
            sidebar
                .frame(width: 72)

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
                    sectionDetailView
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DashboardBackground())
        .preferredColorScheme(.dark)
        // Cascade the Signal theme to every embedded feature view (all sidebar
        // sections except the hand-built "Übersicht" grid, which uses DashboardPalette
        // directly). The shared components recolor via @Environment(\.jarvisTheme).
        .environment(\.jarvisTheme, .signal)
        .task { await pollSystemStats() }
        .task(id: appState.weatherLocation) { await pollWeather() }
        .task { await appState.refreshPermissions() }
        .task(id: calendarOrRemindersAllowed) {
            if calendarOrRemindersAllowed { await appState.refreshCalendarOverview() }
        }
        .task(id: mailAllowed) {
            if mailAllowed { await appState.refreshMailOverview() }
        }
        .task(id: musicAllowed) { await pollMusicOverview() }
    }

    private var calendarOrRemindersAllowed: Bool {
        (appState.permissions["calendar"]?.allowed ?? false) || (appState.permissions["reminders"]?.allowed ?? false)
    }

    private var mailAllowed: Bool {
        appState.permissions["mail"]?.allowed ?? false
    }

    private var musicAllowed: Bool {
        appState.permissions["music"]?.allowed ?? false
    }

    // MARK: - Live data polling (Etappe 3)

    /// CPU sampling needs ~300ms internally per call (two ticks-diffed samples) - 5s between
    /// polls keeps the card fresh without spinning the sampler constantly.
    private func pollSystemStats() async {
        while !Task.isCancelled {
            systemStats = await SystemMonitor.currentStats()
            try? await Task.sleep(for: .seconds(5))
        }
    }

    /// Was previously NowPlayingService's private-MediaRemote-API in-process call (2s
    /// poll, no permission gate) - confirmed via Console/mediaremoted logs that private API
    /// is rejected with "Operation not permitted" for any third-party process (entitlements=0),
    /// including this app itself, not just a wiring bug. Replaced with the same
    /// AppleScript-via-local-server approach music_client.py already used for playback
    /// control, gated behind is_allowed("music") like the other overview cards. 3s (instead
    /// of the old 2s) since each poll is now a real subprocess (osascript), not an in-process
    /// call - still feels live without spawning more processes than needed.
    private func pollMusicOverview() async {
        guard musicAllowed else { return }
        while !Task.isCancelled {
            await appState.refreshMusicOverview()
            try? await Task.sleep(for: .seconds(3))
        }
    }

    /// Keyed on `appState.weatherLocation` so changing the city in Settings restarts this
    /// loop against the new location instead of continuing to poll the old one.
    /// `currentWeather` itself caches for 20 minutes, so the outer poll interval just needs
    /// to be <= that to always pick up a fresh fetch promptly after the cache expires.
    private func pollWeather() async {
        guard let location = appState.weatherLocation else {
            weatherSnapshot = nil
            weatherFetchFailed = false
            return
        }
        while !Task.isCancelled {
            do {
                weatherSnapshot = try await WeatherService.shared.currentWeather(for: location)
                weatherFetchFailed = false
            } catch {
                // Previously `try? await ...` discarded the error and left weatherSnapshot
                // untouched, so a network failure showed an infinite loading spinner with
                // no indication anything had gone wrong. Now WeatherCardContent can render
                // an explicit error state.
                weatherFetchFailed = true
            }
            try? await Task.sleep(for: .seconds(15 * 60))
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(spacing: 0) {
            // Icon-only Rail (Signal-Redesign 2026-08-22): die Identitaet ist der
            // gluehende Punkt selbst, kein "JARVIS OS"-Schriftzug mehr - der passt bei
            // 72pt Sidebar-Breite ohnehin nicht mehr sauber.
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
            .padding(.top, 26)
            .padding(.bottom, 22)
            .help("JARVIS OS")
            .accessibilityLabel("JARVIS OS")

            ScrollView {
                VStack(spacing: 4) {
                    ForEach(DashboardSection.allCases) { section in
                        sidebarRow(section)
                    }
                }
            }
            .scrollIndicators(.never)

            Spacer(minLength: 12)

            ZStack {
                Circle()
                    .fill(DashboardPalette.accent.opacity(0.18))
                    .frame(width: 60, height: 60)
                    .blur(radius: 8)
                Circle()
                    .strokeBorder(DashboardPalette.accent.opacity(0.7), lineWidth: 1.5)
                    .frame(width: 46, height: 46)
                Image(systemName: "waveform")
                    .font(.system(size: 15, weight: .semibold))
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
            Image(systemName: section.symbol)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(isActive ? DashboardPalette.accent : DashboardPalette.textSecondary)
                .frame(width: 38, height: 38)
                .background(
                    RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .fill(isActive ? DashboardPalette.accent.opacity(0.14) : .clear)
                )
        }
        .buttonStyle(.plain)
        // Icon-only Rail: das Label verschwindet visuell, bleibt aber per Tooltip
        // (Hover) und VoiceOver auffindbar, statt ganz zu verschwinden.
        .help(section.title)
        .accessibilityLabel(section.title)
    }

    /// Kompakter Status-Punkt statt der frueheren Text-Karte ("Jarvis Online" /
    /// "Alle Systeme aktiv") - passt nicht mehr in die 72pt-Icon-Rail. Inhalt bleibt
    /// per Tooltip/VoiceOver erreichbar.
    private var statusCard: some View {
        Circle()
            .fill(DashboardPalette.accent)
            .frame(width: 8, height: 8)
            .shadow(color: DashboardPalette.accent.opacity(0.7), radius: 6)
            .help("Jarvis Online - alle Systeme aktiv")
            .accessibilityLabel("Jarvis Online, alle Systeme aktiv")
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
                alwaysListenButton
                micButton
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

    /// Same trigger as the Chat mic button (`ChatView.swift`'s `micDisabled`/mic `Button`) -
    /// this is a second access point to `listenOnce()`, not a parallel recording path.
    private var micDisabled: Bool {
        switch appState.voiceState {
        case .preparingMicrophone, .listening, .userSpeaking, .liveTranscribing, .transcribing, .thinking:
            return true
        default:
            return false
        }
    }

    private var micButton: some View {
        Button {
            Task { await appState.listenOnce() }
        } label: {
            Image(systemName: "mic.fill")
                .font(.system(size: 12))
                .foregroundStyle(micDisabled ? DashboardPalette.textSecondary.opacity(0.5) : DashboardPalette.textSecondary)
        }
        .buttonStyle(.plain)
        .disabled(micDisabled)
        .help("Mit Jarvis sprechen")
    }

    /// Same mechanism as the Chat status ribbon's "Immer an/aus" toggleChip
    /// (`ChatView.swift`'s `statusRibbon`) - just a second, faster access point.
    private var alwaysListenButton: some View {
        Button {
            appState.alwaysListenEnabled.toggle()
            Task { await appState.applyAlwaysListenChange() }
        } label: {
            Image(systemName: appState.alwaysListenEnabled ? "ear.fill" : "ear.trianglebadge.exclamationmark")
                .font(.system(size: 12))
                .foregroundStyle(appState.alwaysListenEnabled ? DashboardPalette.accent : DashboardPalette.textSecondary)
        }
        .buttonStyle(.plain)
        .help(appState.alwaysListenEnabled ? "Immer-Zuhören-Modus deaktivieren" : "Immer-Zuhören-Modus aktivieren")
    }

    /// Falls back to a name-less greeting - not a hardcoded placeholder name - when
    /// `appState.userName` hasn't been set yet, so a fresh install (or a future user of
    /// this app who isn't Leon) never sees a stranger's name greet them.
    private var greetingAttributed: AttributedString {
        let name = appState.userName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else {
            var text = AttributedString("Guten Tag.")
            text.foregroundColor = .white
            return text
        }
        var text = AttributedString("Guten Tag, \(name).")
        text.foregroundColor = .white
        if let range = text.range(of: name) {
            text[range].foregroundColor = DashboardPalette.accent
        }
        return text
    }

    /// Cached instead of allocated per-render: DashboardView's body re-evaluates every
    /// few seconds (systemStats/music polling drive @State changes), and constructing a
    /// DateFormatter is expensive enough that doing it from scratch on every render was
    /// wasted work for a value that only needs to change once a minute.
    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, d. MMMM"
        formatter.locale = Locale(identifier: "de_DE")
        return formatter
    }()

    private var currentTimeString: String {
        Self.timeFormatter.string(from: Date())
    }

    private var currentDateString: String {
        Self.dateFormatter.string(from: Date())
    }

    // MARK: - Card grid (Grundgerüst only - empty bodies, filled in Etappe 3)

    private var cardGrid: some View {
        VStack(spacing: 16) {
            row1
            row2
            row3
        }
        .background(
            GeometryReader { geo in
                Color.clear
                    .onAppear { gridContentWidth = geo.size.width }
                    .onChange(of: geo.size.width) { _, newValue in gridContentWidth = newValue }
            }
        )
    }

    /// Kalender/Mail get the reference design's filled orange squircle badge (they read as
    /// "app icons"); Wetter/Batterie stay badge-less with their native icon coloring
    /// (multicolor weather glyph, green battery) - matched against the reference image
    /// pixel-by-pixel, not guessed from a text description.
    private var row1: some View {
        HStack(spacing: 16) {
            DashboardCard(title: "Kalender", symbol: "calendar", badge: true) {
                KalenderCardContent(
                    hasPermission: appState.permissions["calendar"]?.allowed ?? false,
                    overview: appState.calendarOverview.calendar,
                    openSettings: { activeSection = .section(.privacy) }
                )
            }
            DashboardCard(title: "Mail", symbol: "envelope.fill", badge: true) {
                MailCardContent(
                    hasPermission: appState.permissions["mail"]?.allowed ?? false,
                    overview: appState.mailOverview,
                    openSettings: { activeSection = .section(.privacy) }
                )
            }
            DashboardCard(title: "Wetter", symbol: "cloud.sun.fill", multicolor: true) {
                WeatherCardContent(
                    hasLocation: appState.weatherLocation != nil,
                    snapshot: weatherSnapshot,
                    fetchFailed: weatherFetchFailed,
                    openSettings: { activeSection = .section(.settings) }
                )
            }
            DashboardCard(title: "Batterie", symbol: "battery.100", titleTint: .green) {
                BatteryCardContent(stats: systemStats)
            }
        }
    }

    /// System-Auslastung and Tagesstatistik are noticeably wider than Aufgaben in the
    /// reference (measured ~405:405:302 px of a 1160px-wide row, ≈0.365 : 0.365 : rest) -
    /// not an equal three-way split.
    private var row2: some View {
        let spacing: CGFloat = 16
        let wideWidth = gridContentWidth > 0 ? (gridContentWidth - spacing * 2) * 0.365 : nil
        let narrowWidth = gridContentWidth > 0 && wideWidth != nil
            ? (gridContentWidth - spacing * 2) - wideWidth! * 2
            : nil

        return HStack(spacing: spacing) {
            DashboardCard(title: "System-Auslastung", symbol: "chart.bar.fill") {
                SystemLoadCardContent(stats: systemStats)
            }
            .frame(width: wideWidth)
            DashboardCard(title: "Tagesstatistik", symbol: "chart.line.uptrend.xyaxis") {
                DailyStatsCardContent(
                    activeMinutes: appState.todayActiveUsageMinutes,
                    goalMinutes: appState.dailyUsageGoalMinutes
                )
            }
            .frame(width: wideWidth)
            DashboardCard(title: "Aufgaben", symbol: "checklist", trailingSymbol: "plus") {
                AufgabenCardContent(
                    hasPermission: appState.permissions["reminders"]?.allowed ?? false,
                    overview: appState.calendarOverview.reminders,
                    openSettings: { activeSection = .section(.privacy) }
                )
            }
            .frame(width: narrowWidth)
        }
    }

    /// Musik card + a 6-tile quick-launch icon grid (Dateien/Notizen/Browser/Fotos/
    /// Terminal/Hinzufügen) - the reference splits this row roughly 53:47, not the
    /// single-icon "Schnellzugriff" placeholder card the Grundgerüst had before.
    private var row3: some View {
        let spacing: CGFloat = 16
        let musicWidth = gridContentWidth > 0 ? (gridContentWidth - spacing) * 0.535 : nil
        let tilesWidth = gridContentWidth > 0 && musicWidth != nil
            ? (gridContentWidth - spacing) - musicWidth!
            : nil

        return HStack(spacing: spacing) {
            DashboardCard(title: "Musik", symbol: "music.note") {
                MusicCardContent(
                    hasPermission: musicAllowed,
                    overview: appState.musicOverview,
                    openSettings: { activeSection = .section(.privacy) }
                )
            }
            .frame(width: musicWidth)
            quickLaunchGrid
                .frame(width: tilesWidth)
        }
    }

    private var quickLaunchGrid: some View {
        let tiles: [(label: String, symbol: String, tint: Color)] = [
            ("Dateien", "folder.fill", DashboardPalette.badgeBlue),
            ("Notizen", "note.text", DashboardPalette.badgeAmber),
            ("Browser", "safari.fill", DashboardPalette.badgeBlue),
            ("Fotos", "photo.stack.fill", DashboardPalette.accentLight),
            ("Terminal", "terminal.fill", DashboardPalette.textSecondary),
            ("Hinzufügen", "plus", DashboardPalette.textSecondary),
        ]
        return HStack(spacing: 8) {
            ForEach(tiles, id: \.label) { tile in
                VStack(spacing: 8) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(Color.white.opacity(0.07))
                            .frame(width: 42, height: 42)
                        Image(systemName: tile.symbol)
                            .font(.system(size: 16, weight: .medium))
                            .foregroundStyle(tile.tint)
                    }
                    Text(tile.label)
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(DashboardPalette.textSecondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .dashboardGlass(cornerRadius: 18)
    }

    /// Schickt den Bildschirm-Befehl (Phase F, siehe docs/vision-system.md) wie eine normale
    /// Chat-Nachricht ab und wechselt zur Chat-Ansicht, damit die Antwort (oder eine
    /// ausstehende Berechtigungsabfrage) sofort sichtbar ist - kein separater Aufnahmepfad,
    /// nur ein Shortcut für dieselbe Frage, die man auch tippen könnte.
    private func triggerScreenshotQuickAction() {
        activeSection = .section(.chat)
        Task { await appState.send("Schau dir meinen Bildschirm an.") }
    }

    private var quickAccessBar: some View {
        HStack(spacing: 12) {
            HStack(spacing: 6) {
                Image(systemName: "circle.grid.3x3.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(DashboardPalette.accent)
                Text("Schnellzugriff")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }

            ForEach([
                ("Notizen erstellen", "note.text"),
                ("Screenshot machen", "camera.viewfinder"),
                ("Erinnerung setzen", "bell"),
                ("Timer starten", "timer"),
            ], id: \.0) { label, symbol in
                HStack(spacing: 6) {
                    Image(systemName: symbol)
                        .font(.system(size: 11))
                    Text(label)
                        .font(.system(size: 12, weight: .medium))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Capsule().fill(Color.white.opacity(0.08)))
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.10), lineWidth: 1))
                .contentShape(Capsule())
                // Nur dieser Chip ist verdrahtet - die anderen drei ("Notizen erstellen" etc.)
                // bleiben bewusst unverändert dekorativ, das war nicht Teil der Anfrage.
                .onTapGesture {
                    if label == "Screenshot machen" {
                        triggerScreenshotQuickAction()
                    }
                }
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

    /// Every non-overview sidebar item maps to the SAME real view MainShellView's
    /// `detailView` embeds for that `JarvisSection` (MainShellView.swift) - the Dashboard is
    /// an alternate shell around the existing feature set, not a reimplementation of it, so
    /// nothing here is a "coming later" placeholder.
    @ViewBuilder
    private var sectionDetailView: some View {
        if case .section(let jarvisSection) = activeSection {
            switch jarvisSection {
            case .home: HomeView()
            case .actions: ActionCenterView()
            case .chat: ChatView()
            case .history: HistoryView()
            case .mail: MailView()
            case .files: FilesView()
            case .photos: PhotosView()
            case .memory: MemoryView()
            case .tasks: TasksView()
            case .calendar: CalendarWorkspaceView()
            case .reminders: RemindersWorkspaceView()
            case .privacy: PrivacyView()
            case .models: ModelsView()
            case .licenses: LicensesView()
            case .settings: SettingsView()
            }
        }
    }
}

// MARK: - Reusable card shell

private struct DashboardCard<Content: View>: View {
    let title: String
    let symbol: String
    var titleTint: Color = DashboardPalette.accent
    var trailingSymbol: String = "ellipsis"
    /// Matches the reference design: only Kalender/Mail render as filled orange squircle
    /// "app icons" - every other card icon is badge-less (see `row1` for why).
    var badge: Bool = false
    /// Renders the SF Symbol in its native multi-tone palette (used for the weather glyph)
    /// instead of a flat `titleTint` fill.
    var multicolor: Bool = false
    @ViewBuilder var content: () -> Content

    init(
        title: String,
        symbol: String,
        titleTint: Color = DashboardPalette.accent,
        trailingSymbol: String = "ellipsis",
        badge: Bool = false,
        multicolor: Bool = false,
        @ViewBuilder content: @escaping () -> Content = { DashboardPlaceholder() }
    ) {
        self.title = title
        self.symbol = symbol
        self.titleTint = titleTint
        self.trailingSymbol = trailingSymbol
        self.badge = badge
        self.multicolor = multicolor
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                HStack(spacing: 10) {
                    iconView
                    Text(title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.white)
                }
                Spacer(minLength: 0)
                Image(systemName: trailingSymbol)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DashboardPalette.textSecondary)
            }

            content()
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .dashboardGlass(cornerRadius: 18)
    }

    @ViewBuilder
    private var iconView: some View {
        if badge {
            ZStack {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(titleTint)
                    .frame(width: 30, height: 30)
                Image(systemName: symbol)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.white)
            }
        } else if multicolor {
            Image(systemName: symbol)
                .symbolRenderingMode(.multicolor)
                .font(.system(size: 17, weight: .semibold))
        } else {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(titleTint)
        }
    }
}

private struct DashboardPlaceholder: View {
    var text: String = "Noch keine Daten in diesem Grundgerüst."
    /// When set, the placeholder becomes a button (e.g. "kein Standort konfiguriert" jumps
    /// straight to the Einstellungen section instead of making the user hunt for it).
    var action: (() -> Void)?

    var body: some View {
        if let action {
            Button(action: action) {
                label
                    .underline()
            }
            .buttonStyle(.plain)
        } else {
            label
        }
    }

    private var label: some View {
        Text(text)
            .font(.system(size: 12))
            .foregroundStyle(DashboardPalette.textSecondary.opacity(0.7))
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .center)
            .multilineTextAlignment(.center)
    }
}

private struct DashboardLoadingPlaceholder: View {
    var body: some View {
        ProgressView()
            .controlSize(.small)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .center)
    }
}

// MARK: - Card content (Etappe 3 - real data from the four verified sources)

private struct WeatherCardContent: View {
    let hasLocation: Bool
    let snapshot: WeatherSnapshot?
    var fetchFailed: Bool = false
    var openSettings: (() -> Void)?

    var body: some View {
        if !hasLocation {
            DashboardPlaceholder(text: "Kein Standort konfiguriert - hier tippen.", action: openSettings)
        } else if let snapshot {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text("\(Int(snapshot.temperature.rounded()))°")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(.white)
                    Text("C")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(DashboardPalette.textSecondary)
                }
                Text(Self.condition(code: snapshot.weatherCode))
                    .font(.system(size: 12))
                    .foregroundStyle(DashboardPalette.textSecondary)
                HStack(spacing: 4) {
                    Image(systemName: "wind")
                    Text("\(Int(snapshot.windSpeed.rounded())) km/h")
                }
                .font(.system(size: 11))
                .foregroundStyle(DashboardPalette.textSecondary.opacity(0.8))
            }
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        } else if fetchFailed {
            DashboardPlaceholder(text: "Wetter konnte nicht geladen werden.")
        } else {
            DashboardLoadingPlaceholder()
        }
    }

    /// German text for Open-Meteo's WMO weather codes (api.open-meteo.com/en/docs) - no
    /// mapping existed anywhere in the codebase yet, this is the dashboard's own.
    static func condition(code: Int) -> String {
        switch code {
        case 0: return "Klarer Himmel"
        case 1: return "Überwiegend klar"
        case 2: return "Teilweise bewölkt"
        case 3: return "Bewölkt"
        case 45, 48: return "Neblig"
        case 51, 53, 55: return "Nieselregen"
        case 56, 57: return "Gefrierender Nieselregen"
        case 61, 63, 65: return "Regen"
        case 66, 67: return "Gefrierender Regen"
        case 71, 73, 75: return "Schneefall"
        case 77: return "Schneegriesel"
        case 80, 81, 82: return "Regenschauer"
        case 85, 86: return "Schneeschauer"
        case 95: return "Gewitter"
        case 96, 99: return "Gewitter mit Hagel"
        default: return "Unbekannt"
        }
    }
}

private struct KalenderCardContent: View {
    let hasPermission: Bool
    let overview: CalendarOverviewSection
    var openSettings: (() -> Void)?

    var body: some View {
        if !hasPermission {
            DashboardPlaceholder(text: "Kalender nicht verbunden - hier tippen.", action: openSettings)
        } else if overview.message == "Noch nicht geladen." {
            DashboardLoadingPlaceholder()
        } else if overview.items.isEmpty {
            DashboardPlaceholder(text: overview.message)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(overview.items.prefix(3)) { item in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.title)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(.white)
                            .lineLimit(1)
                        if let when = item.start ?? item.end {
                            Text(when)
                                .font(.system(size: 10.5))
                                .foregroundStyle(DashboardPalette.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        }
    }
}

private struct MailCardContent: View {
    let hasPermission: Bool
    let overview: MailOverviewPayload
    var openSettings: (() -> Void)?

    var body: some View {
        if !hasPermission {
            DashboardPlaceholder(text: "Mail nicht verbunden - hier tippen.", action: openSettings)
        } else if overview.message == "Noch nicht geladen." {
            DashboardLoadingPlaceholder()
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(overview.unreadCount) ungelesen")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
                if overview.messages.isEmpty {
                    Text(overview.unreadCount == 0 ? "Keine ungelesenen Mails." : overview.message)
                        .font(.system(size: 11))
                        .foregroundStyle(DashboardPalette.textSecondary)
                } else {
                    ForEach(overview.messages.prefix(3)) { message in
                        VStack(alignment: .leading, spacing: 0) {
                            Text(message.sender)
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.white)
                                .lineLimit(1)
                            Text(message.subject)
                                .font(.system(size: 10.5))
                                .foregroundStyle(DashboardPalette.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        }
    }
}

private struct AufgabenCardContent: View {
    let hasPermission: Bool
    let overview: CalendarOverviewSection
    var openSettings: (() -> Void)?

    var body: some View {
        if !hasPermission {
            DashboardPlaceholder(text: "Erinnerungen nicht verbunden - hier tippen.", action: openSettings)
        } else if overview.message == "Noch nicht geladen." {
            DashboardLoadingPlaceholder()
        } else if overview.items.isEmpty {
            DashboardPlaceholder(text: overview.message)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(overview.items.prefix(4)) { item in
                    HStack(spacing: 6) {
                        Image(systemName: "circle")
                            .font(.system(size: 8))
                            .foregroundStyle(DashboardPalette.accent)
                        Text(item.title)
                            .font(.system(size: 11.5))
                            .foregroundStyle(.white)
                            .lineLimit(1)
                    }
                }
            }
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        }
    }
}

private struct SystemLoadCardContent: View {
    let stats: SystemStats?

    var body: some View {
        if let stats {
            HStack(spacing: 24) {
                gauge(label: "CPU", value: stats.cpuUsagePercent)
                gauge(label: "RAM", value: stats.memoryUsagePercent)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, minHeight: 64)
        } else {
            DashboardLoadingPlaceholder()
        }
    }

    private func gauge(label: String, value: Double) -> some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(Color.white.opacity(0.10), lineWidth: 5)
                Circle()
                    .trim(from: 0, to: max(0, min(value / 100, 1)))
                    .stroke(DashboardPalette.accent, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                Text("\(Int(value.rounded()))%")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 54, height: 54)
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(DashboardPalette.textSecondary)
        }
    }
}

private struct BatteryCardContent: View {
    let stats: SystemStats?

    var body: some View {
        if let stats {
            if let percent = stats.batteryPercent {
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(percent) %")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(.white)
                    HStack(spacing: 4) {
                        Image(systemName: (stats.isCharging ?? false) ? "bolt.fill" : "battery.100")
                        Text((stats.isCharging ?? false) ? "Lädt" : "Auf Akku")
                    }
                    .font(.system(size: 11))
                    .foregroundStyle(DashboardPalette.textSecondary)

                    Capsule()
                        .fill(Color.white.opacity(0.10))
                        .frame(height: 6)
                        .overlay(alignment: .leading) {
                            GeometryReader { geo in
                                Capsule()
                                    .fill(percent < 20 ? Color.red : Color.green)
                                    .frame(width: geo.size.width * CGFloat(percent) / 100)
                            }
                        }
                }
                .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
            } else {
                DashboardPlaceholder(text: "Kein Akku erkannt (z. B. Desktop-Mac).")
            }
        } else {
            DashboardLoadingPlaceholder()
        }
    }
}

private struct MusicCardContent: View {
    let hasPermission: Bool
    let overview: MusicOverviewPayload
    var openSettings: (() -> Void)?

    var body: some View {
        if !hasPermission {
            DashboardPlaceholder(text: "Musik nicht verbunden - hier tippen.", action: openSettings)
        } else if overview.message == "Noch nicht geladen." {
            DashboardLoadingPlaceholder()
        } else if let track = overview.track {
            VStack(alignment: .leading, spacing: 6) {
                Text(track.title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                if let artist = track.artist {
                    Text(artist)
                        .font(.system(size: 12))
                        .foregroundStyle(DashboardPalette.textSecondary)
                        .lineLimit(1)
                }
                HStack(spacing: 6) {
                    Image(systemName: track.isPlaying ? "play.fill" : "pause.fill")
                        .font(.system(size: 10))
                    Text("Apple Music")
                        .font(.system(size: 11))
                }
                .foregroundStyle(DashboardPalette.accent)
            }
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        } else {
            DashboardPlaceholder(text: "Gerade läuft nichts.")
        }
    }
}

private struct DailyStatsCardContent: View {
    let activeMinutes: Double
    let goalMinutes: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(Self.formatted(activeMinutes))
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(.white)
            Text("Aktiv heute")
                .font(.system(size: 11))
                .foregroundStyle(DashboardPalette.textSecondary)

            if let goalMinutes, goalMinutes > 0 {
                let progress = max(0, min(activeMinutes / goalMinutes, 1))
                Capsule()
                    .fill(Color.white.opacity(0.10))
                    .frame(height: 6)
                    .overlay(alignment: .leading) {
                        GeometryReader { geo in
                            Capsule()
                                .fill(DashboardPalette.accent)
                                .frame(width: geo.size.width * progress)
                        }
                    }
                Text("Ziel: \(Self.formatted(goalMinutes))")
                    .font(.system(size: 10.5))
                    .foregroundStyle(DashboardPalette.textSecondary.opacity(0.8))
            }
        }
        .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
    }

    private static func formatted(_ minutes: Double) -> String {
        let h = Int(minutes) / 60
        let m = Int(minutes) % 60
        return h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }
}

// MARK: - Sections (wraps every real `JarvisSection` plus the Dashboard-only "Übersicht"
// home, so nothing reachable from the classic sidebar goes missing behind the new layout)

private enum DashboardSection: Equatable, Identifiable {
    case overview
    case section(JarvisSection)

    static var allCases: [DashboardSection] {
        [.overview] + JarvisSection.allCases.map(DashboardSection.section)
    }

    var id: String {
        switch self {
        case .overview: "overview"
        case .section(let s): s.id
        }
    }

    var title: String {
        switch self {
        case .overview: "Übersicht"
        case .section(let s): s.rawValue
        }
    }

    var symbol: String {
        switch self {
        case .overview: "square.grid.2x2.fill"
        case .section(let s): s.symbol
        }
    }
}

// MARK: - Palette, background and glass style

enum DashboardPalette {
    // Signal-Theme (2026-08-22): mint statt warmem Orange, Farbton per Settings waehlbar
    // (SignalAccentHue). Bewusst weiterhin ein eigener Satz statt @Environment(\.jarvisTheme)
    // - dieselbe Struktur wie zuvor, da DashboardView sein "Übersicht"-Grid direkt darauf
    // aufbaut (siehe Kommentar bei .environment(\.jarvisTheme, .signal) oben). `static var`
    // statt `static let`, damit eine Farbton-Aenderung in Settings sofort live nachgezogen
    // wird statt nur einmal pro Prozesslaufzeit berechnet zu werden.
    static var accent: Color { JarvisTheme.signal.primaryAccent }
    static var accentLight: Color { JarvisTheme.signal.secondaryAccent }
    static let background = Color(red: 0.02, green: 0.02, blue: 0.024)
    static let textSecondary = Color(red: 0.612, green: 0.639, blue: 0.686)
    static let sidebarFill = Color.black.opacity(0.28)
    /// Faint tint on top of `.ultraThinMaterial` - pixel-sampled against the reference
    /// image, card fill and the gap between cards come out almost identical in brightness
    /// there, so this stays barely-there and lets the material's own blur (plus the border
    /// stroke) do the work of separating a card from the backdrop.
    static let cardFill = Color.black.opacity(0.10)

    // Quick-launch tile icon colors (row 3's 6-tile grid).
    static let badgeBlue = Color(red: 0.36, green: 0.56, blue: 0.95)
    static let badgeAmber = Color(red: 0.93, green: 0.78, blue: 0.30)
}

struct DashboardBackground: View {
    var body: some View {
        // Signal-Redesign (2026-08-22): der warme Bokeh-Foto-Hintergrund + brauner Scrim
        // aus dem alten Orange-Theme ist raus - "Signal" ist bewusst fast schwarz, ein
        // Foto mit eigenen warmen Bildfarben wuerde das immer unterlaufen, egal wie die
        // Overlay-Farben angepasst werden. Flacher, fast schwarzer Verlauf + dezentes
        // radiales Mint-Gluehen, analog zu LiquidGlassBackground's .signal-Fall.
        ZStack {
            LinearGradient(
                colors: [DashboardPalette.background, Color(red: 0.012, green: 0.012, blue: 0.016)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [DashboardPalette.accent.opacity(0.08), .clear],
                center: .topLeading,
                startRadius: 40,
                endRadius: 560
            )

            topGlowArc
        }
        .ignoresSafeArea()
    }

    /// Leuchtender oranger Lichtbogen am oberen Rand, gleichmäßig über die gesamte Breite
    /// verteilt (nicht auf die Mitte konzentriert) - spiegelt den Deckenlicht-Bogen im
    /// Referenzbild, sitzt oberhalb des Scrims damit er klar sichtbar bleibt.
    private var topGlowArc: some View {
        VStack(spacing: 0) {
            ZStack {
                LinearGradient(
                    colors: [DashboardPalette.accentLight.opacity(0.30), .clear],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .frame(height: 130)

                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.0),
                        .init(color: DashboardPalette.accentLight.opacity(0.75), location: 0.08),
                        .init(color: DashboardPalette.accentLight.opacity(0.75), location: 0.92),
                        .init(color: .clear, location: 1.0),
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .frame(height: 2.5)
                .blur(radius: 1)
            }
            Spacer()
        }
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
