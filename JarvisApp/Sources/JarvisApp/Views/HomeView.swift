import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var appState: AppState

    private var activePermissions: Int {
        appState.permissions.values.filter(\.allowed).count
    }

    private var totalPermissions: Int {
        max(appState.permissions.count, 1)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                hero
                personalityStrip
                ideaStrip
                summaryGrid
                liveStatus
                briefingCard
                quickActions
                footerHint
            }
            .padding(28)
            .frame(maxWidth: 1080, alignment: .leading)
        }
        .background(LiquidGlassBackground())
        .navigationTitle("Home")
        .task {
            await appState.refreshPermissions()
            await appState.refreshScanStatesSafely()
        }
    }

    private var personalityStrip: some View {
        HStack(spacing: 12) {
            StripBadge(title: "Ruhig", subtitle: "Jarvis bleibt gelassen, auch wenn es hektisch wird.", symbol: "moon.stars.fill", tint: .cyan)
            StripBadge(title: "Direkt", subtitle: "Kurze Antworten, klare Schritte, wenig Umwege.", symbol: "arrow.forward.circle.fill", tint: .blue)
            StripBadge(title: "Hilfsbereit", subtitle: "Wenn etwas offen ist, fragt Jarvis sauber nach.", symbol: "hand.raised.fill", tint: .green)
        }
    }

    private var ideaStrip: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Ideen für den nächsten Satz", subtitle: "Kleine Anstöße, damit Jarvis von sich aus nützliche Vorschläge macht.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: 12)], spacing: 12) {
                ideaCard(
                    title: "Was steht heute an?",
                    subtitle: "Jarvis fasst Termine, Mail-Hinweise und offene Punkte zusammen.",
                    symbol: "calendar.badge.clock",
                    tint: .indigo
                ) {
                    appState.prepareComposerDraft("Jarvis, was steht heute an?")
                }
                ideaCard(
                    title: "Kurzes Mail-Update",
                    subtitle: "Ein schneller Überblick über neue oder wichtige Nachrichten.",
                    symbol: "envelope.open.fill",
                    tint: .blue
                ) {
                    appState.prepareComposerDraft("Jarvis, gib mir ein kurzes Mail-Update.")
                }
                ideaCard(
                    title: "Erinnerung anlegen",
                    subtitle: "Aus einer Idee wird direkt ein sauberer Eintrag.",
                    symbol: "bell.badge.fill",
                    tint: .green
                ) {
                    appState.prepareComposerDraft("Jarvis, erstelle mir eine Erinnerung für morgen um 18 Uhr.")
                }
                ideaCard(
                    title: "Dateien oder Fotos suchen",
                    subtitle: "Ideal, wenn du etwas schnell wiederfinden willst.",
                    symbol: "magnifyingglass.circle.fill",
                    tint: .purple
                ) {
                    appState.prepareComposerDraft("Jarvis, such mir bitte die wichtigsten Dateien oder Fotos heraus.")
                }
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    private func ideaCard(title: String, subtitle: String, symbol: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(tint)
                        .frame(width: 34, height: 34)
                        .background(.thinMaterial, in: Circle())
                    Spacer()
                    Image(systemName: "arrow.right.circle")
                        .foregroundStyle(.secondary)
                }
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var footerHint: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkles")
                .foregroundStyle(.cyan)
            Text("Tipp: Mit Sprache fühlt sich Jarvis am natürlichsten an. Text bleibt als gute Reserve.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .liquidGlassCard(tint: .cyan, cornerRadius: 20)
    }

    private var hero: some View {
        HStack(alignment: .center, spacing: 18) {
            ZStack {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color.cyan.opacity(0.96), Color.indigo.opacity(0.78), Color.mint.opacity(0.54)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 96, height: 96)
                    .shadow(color: .cyan.opacity(0.20), radius: 18, x: 0, y: 8)
                Image(systemName: "sparkles")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(.white)
                Image(systemName: "sparkles")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.white.opacity(0.72))
                    .offset(x: 18, y: -16)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("Willkommen zurück, \(appState.displayUserName).")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Jarvis ist bereit. Ruhig, flott und mit einem kleinen Hang zur hilfreichen Klugscheißerei.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 10) {
                    heroChip(title: appState.status == .offline ? "Offline" : "Verbunden", icon: appState.status == .offline ? "wifi.slash" : "checkmark.seal.fill", tint: appState.status == .offline ? .orange : .green)
                    heroChip(title: appState.voiceState.title, icon: appState.voiceState.symbol, tint: appState.voiceState.tint)
                    heroChip(title: isModelInfoAvailable ? appState.modelStatus.activeModel : "Nicht verbunden", icon: modelProviderIsOpenAI ? "cloud.fill" : "cpu.fill", tint: modelProviderIsOpenAI ? .orange : .indigo)
                    heroChip(title: jarvisAppVersion, icon: "seal.fill", tint: .cyan)
                }
            }

            Spacer(minLength: 0)
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private func heroChip(title: String, icon: String, tint: Color) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.16), lineWidth: 1))
    }

    private var summaryGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 14)], spacing: 14) {
            summaryCard(
                title: "Status",
                value: appState.status.rawValue,
                symbol: appState.status == .offline ? "exclamationmark.triangle.fill" : "checkmark.circle.fill",
                tint: appState.status == .offline ? .orange : .green
            )
            summaryCard(
                title: "Modell",
                value: modelSummary,
                symbol: modelProviderIsOpenAI ? "cloud.fill" : "cpu.fill",
                tint: modelProviderIsOpenAI ? .orange : .indigo
            )
            summaryCard(
                title: "Berechtigungen",
                value: "\(activePermissions) / \(totalPermissions)",
                symbol: "hand.raised.fill",
                tint: .green
            )
            summaryCard(
                title: "Sprache",
                value: appState.voiceState.title,
                symbol: appState.voiceState.symbol,
                tint: appState.voiceState.tint
            )
        }
    }

    private var isModelInfoAvailable: Bool {
        appState.status != .offline
    }

    private var modelProviderIsOpenAI: Bool {
        isModelInfoAvailable && appState.modelStatus.provider.lowercased() == "openai"
    }

    private var modelSummary: String {
        guard isModelInfoAvailable else { return "Nicht verbunden" }
        if modelProviderIsOpenAI {
            return "OpenAI • \(appState.modelStatus.activeModel)"
        }
        return "Lokal • \(appState.modelStatus.activeModel)"
    }

    private func summaryCard(title: String, value: String, symbol: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 34, height: 34)
                .background(.thinMaterial, in: Circle())

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }

            Spacer(minLength: 0)
        }
        .padding(14)
        .liquidGlassCard(tint: tint, cornerRadius: 22)
    }

    private var liveStatus: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Live-Status", subtitle: "Was Jarvis gerade tut, ohne Bürokratietheater und Nebelkerzen.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 14)], spacing: 14) {
                liveCard(
                    title: "Sprache",
                    subtitle: appState.voiceState.subtitle,
                    tint: appState.voiceState.tint,
                    icon: appState.voiceState.symbol
                )
                liveCard(
                    title: "Mail-Scan",
                    subtitle: progressSummary(appState.mailScanProgress),
                    tint: .blue,
                    icon: "tray.full.fill"
                )
                liveCard(
                    title: "Fotoindex",
                    subtitle: progressSummary(appState.photoScanProgress),
                    tint: .purple,
                    icon: "photo.on.rectangle.angled"
                )
                liveCard(
                    title: "Dateien",
                    subtitle: progressSummary(appState.fileScanProgress),
                    tint: .cyan,
                    icon: "folder.fill"
                )
                liveCard(
                    title: "Beta",
                    subtitle: "Bereit für frühe Tester. Schnell, lokal und noch mit Feinschliff.",
                    tint: .cyan,
                    icon: "testtube.2"
                )
            }
        }
        .liquidGlassPanel(tint: .cyan)
    }

    /// Calendar+Reminders must both be explicitly on before the briefing is allowed to
    /// touch either - otherwise this card would be exactly the every-launch proactive
    /// trigger it's meant to avoid (see `connectPrompt`).
    private var calendarAndRemindersAllowed: Bool {
        (appState.permissions["calendar"]?.allowed ?? false) && (appState.permissions["reminders"]?.allowed ?? false)
    }

    private var briefingCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Tagesbriefing", subtitle: "Morgens und abends auf einen Blick. Jetzt erstmal kompakt, später noch schlauer.")
            if calendarAndRemindersAllowed {
                Text(appState.dailyBriefingText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button {
                        Task { await appState.refreshDailyBriefing() }
                    } label: {
                        Label("Aktualisieren", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)

                    Spacer()
                }
            } else {
                connectPrompt
            }
        }
        .padding(14)
        .liquidGlassPanel(tint: .indigo)
        .task(id: calendarAndRemindersAllowed) {
            if calendarAndRemindersAllowed {
                await appState.refreshDailyBriefing()
            }
        }
    }

    /// Tapping "Verbinden" is the explicit user action that's allowed to trigger the
    /// native macOS consent dialogs for Kalender/Erinnerungen - never the card just
    /// appearing on screen.
    private var connectPrompt: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Kalender & Erinnerungen verbinden")
                    .font(.subheadline.weight(.semibold))
                Text("Damit kann Jarvis dein Tagesbriefing mit echten Terminen und offenen Erinnerungen befüllen.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 12)
            Button("Verbinden") {
                Task {
                    await appState.setPermission("calendar", allowed: true)
                    await appState.setPermission("reminders", allowed: true)
                    await appState.refreshDailyBriefing()
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        }
    }

    private func liveCard(title: String, subtitle: String, tint: Color, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 34, height: 34)
                    .background(.thinMaterial, in: Circle())
                Spacer()
                Text(title)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            Text(subtitle)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)
            ProgressView(value: progressValue(for: title))
                .progressViewStyle(.linear)
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
        )
    }

    private func progressValue(for title: String) -> Double {
        switch title {
        case "Mail-Scan": return appState.mailScanProgress.fraction
        case "Fotoindex": return appState.photoScanProgress.fraction
        case "Dateien": return appState.fileScanProgress.fraction
        default: return 0.0
        }
    }

    private func progressSummary(_ progress: ScanProgress) -> String {
        if progress.status == .idle, progress.totalItems == 0 {
            return "Noch kein Lauf gestartet."
        }
        if progress.totalItems > 0 {
            return "\(progress.percentText) - \(progress.currentItem) von \(progress.totalItems)"
        }
        return progress.status.label
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Schnellaktionen", subtitle: "Einmal tippen, Jarvis übernimmt den Rest. Freundlich, flott und geradeaus.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 14)], spacing: 14) {
                quickAction(title: "Mikrofon öffnen", symbol: "mic.fill", tint: .green) {
                    appState.selectedSection = .chat
                }
                quickAction(title: "Mail prüfen", symbol: "envelope.fill", tint: .blue) {
                    appState.selectedSection = .mail
                }
                quickAction(title: "Dateien suchen", symbol: "folder.fill", tint: .cyan) {
                    appState.selectedSection = .files
                }
                quickAction(title: "Fotos ansehen", symbol: "photo.fill.on.rectangle.fill", tint: .purple) {
                    appState.selectedSection = .photos
                }
                quickAction(title: "Datenschutz", symbol: "hand.raised.fill", tint: .green) {
                    appState.selectedSection = .privacy
                }
                quickAction(title: "Modelle", symbol: "cpu.fill", tint: .indigo) {
                    appState.selectedSection = .models
                }
            }
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private func quickAction(title: String, symbol: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 34, height: 34)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(title)
                    .font(.headline)
                Spacer()
                Image(systemName: "arrow.right.circle")
                    .foregroundStyle(.secondary)
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
            )
            .overlay(alignment: .topTrailing) {
                Image(systemName: "sparkles")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(tint.opacity(0.55))
                    .padding(8)
            }
        }
        .buttonStyle(.plain)
    }

    private func sectionHeader(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title2.bold())
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }
}

private struct StripBadge: View {
    let title: String
    let subtitle: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 28, height: 28)
                .background(.thinMaterial, in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .liquidGlassCard(tint: tint, cornerRadius: 20)
    }
}

struct ActionCenterView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                statusRows
                scanGrid
                commandGrid
            }
            .padding(28)
            .frame(maxWidth: 1080, alignment: .leading)
        }
        .background(LiquidGlassBackground())
        .navigationTitle("Aktionszentrale")
        .task {
            await appState.refreshStatus()
            await appState.refreshScanStatesSafely()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 18) {
            ZStack {
                Circle()
                    .fill(
                        AngularGradient(
                            colors: [.cyan, .blue, .indigo, .purple, .cyan],
                            center: .center
                        )
                    )
                    .frame(width: 62, height: 62)
                    .shadow(color: .cyan.opacity(0.20), radius: 14, x: 0, y: 8)
                Image(systemName: "rectangle.grid.2x2.fill")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(.white)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Jarvis Aktionszentrale")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Hier sieht \(appState.displayUserName) in einem Blick, was läuft, was wartet und wo Jarvis schon vor der Tür steht.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private var statusRows: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 14)], spacing: 14) {
            centerCard(title: "Status", value: appState.status.rawValue, symbol: "bolt.horizontal.circle.fill", tint: .green)
            centerCard(title: "Voice", value: appState.voiceState.title, symbol: appState.voiceState.symbol, tint: appState.voiceState.tint)
            centerCard(title: "Modell", value: appState.status != .offline ? appState.modelStatus.activeModel : "Nicht verbunden", symbol: "cpu.fill", tint: .indigo)
            centerCard(title: "Letzter Fehler", value: appState.lastError ?? "Kein Fehler", symbol: "exclamationmark.triangle.fill", tint: appState.lastError == nil ? .green : .orange)
        }
    }

    private func centerCard(title: String, value: String, symbol: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 34, height: 34)
                .background(.thinMaterial, in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .liquidGlassCard(tint: tint, cornerRadius: 22)
    }

    private var scanGrid: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Aktive Scans", subtitle: "Die letzten und laufenden Index- und Scanprozesse, hübsch sichtbar und ohne Rätselraten.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 14)], spacing: 14) {
                ScanProgressCard(
                    title: "Mail-Scan",
                    symbol: "tray.full",
                    progress: appState.mailScanProgress,
                    stats: [
                        ("Ordner", stat(appState.mailScanProgress, "folders_scanned")),
                        ("Mails", stat(appState.mailScanProgress, "mails_indexed"))
                    ]
                )
                ScanProgressCard(
                    title: "Fotoindex",
                    symbol: "photo.on.rectangle.angled",
                    progress: appState.photoScanProgress,
                    stats: [
                        ("Fotos", stat(appState.photoScanProgress, "photos_indexed")),
                        ("Labels", stat(appState.photoScanProgress, "labels_recognized"))
                    ]
                )
                ScanProgressCard(
                    title: "Dateiindex",
                    symbol: "folder.badge.gearshape",
                    progress: appState.fileScanProgress,
                    stats: [
                        ("Dateien", stat(appState.fileScanProgress, "files_found")),
                        ("Ordner", stat(appState.fileScanProgress, "folders_found"))
                    ]
                )
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    private var commandGrid: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Direkt starten", subtitle: "Ein Tipp, und Jarvis ist schon unterwegs. Freundlich, flott und ohne Theaterpause.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 14)], spacing: 14) {
                actionButton("Mit Jarvis sprechen", symbol: "mic.fill", tint: .green) {
                    appState.selectedSection = .chat
                }
                actionButton("Mail-Ordner scannen", symbol: "envelope.fill", tint: .blue) {
                    appState.selectedSection = .mail
                    Task { await appState.startMailFolderScan() }
                }
                actionButton("Fotoindex starten", symbol: "photo.fill.on.rectangle.fill", tint: .purple) {
                    appState.selectedSection = .photos
                    Task { await appState.startPhotoIndexScan() }
                }
                actionButton("Dateiindex starten", symbol: "folder.fill", tint: .cyan) {
                    appState.selectedSection = .files
                    Task { await appState.startFileIndexScan() }
                }
                actionButton("Datenschutz öffnen", symbol: "hand.raised.fill", tint: .green) {
                    appState.selectedSection = .privacy
                }
                actionButton("Modelle prüfen", symbol: "cpu.fill", tint: .indigo) {
                    appState.selectedSection = .models
                }
            }
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private func actionButton(_ title: String, symbol: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 34, height: 34)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(title)
                    .font(.headline)
                Spacer()
                Image(systemName: "arrow.right.circle")
                    .foregroundStyle(.secondary)
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
            )
            .overlay(alignment: .topTrailing) {
                Image(systemName: "sparkles")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(tint.opacity(0.55))
                    .padding(8)
            }
        }
        .buttonStyle(.plain)
    }

    private func sectionHeader(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title2.bold())
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private func stat(_ progress: ScanProgress, _ key: String) -> String {
        progress.stats[key]?.description ?? "0"
    }

    private struct StripBadge: View {
        let title: String
        let subtitle: String
        let symbol: String
        let tint: Color

        var body: some View {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: symbol)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 28, height: 28)
                    .background(.thinMaterial, in: Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlassCard(tint: tint, cornerRadius: 20)
        }
    }
}
