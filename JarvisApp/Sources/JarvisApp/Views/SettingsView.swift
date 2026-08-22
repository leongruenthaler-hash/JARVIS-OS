import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @AppStorage("JarvisActiveTheme") private var activeThemeRaw = JarvisTheme.signal.rawValue
    @AppStorage("JarvisDashboardLayoutEnabled") private var dashboardLayoutEnabled = true
    @State private var apiKey = ""
    @State private var weatherCityDraft = ""
    @State private var usageGoalDraft = ""
    @State private var voiceEnrollmentPrompt = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                betaSection
                profileSection
                generalSection
                designSection
                voiceSection
                openAISection
                coreSection
                licensesSection
            }
            .padding(28)
            .frame(maxWidth: 920, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Einstellungen")
        .onAppear {
            if weatherCityDraft.isEmpty {
                weatherCityDraft = appState.weatherCityName
            }
            if usageGoalDraft.isEmpty, let goal = appState.dailyUsageGoalMinutes {
                usageGoalDraft = String(Int(goal))
            }
        }
        .task {
            await appState.refreshConversationHistory()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "gearshape.fill", tint: .gray)

            VStack(alignment: .leading, spacing: 6) {
                Text("Einstellungen")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Sprache, lokaler Core und API-Schlüssel bleiben hier kontrollierbar. Weniger Terminal, mehr direkte Kontrolle.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .gray)
    }

    private var betaSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Beta-Status", subtitle: "Kurz und ehrlich: Was für Tester schon gut steht.")

            HStack(spacing: 12) {
                statusBadge(title: "Version", value: jarvisAppVersion, symbol: "seal.fill", tint: .cyan)
                statusBadge(title: "Modus", value: "Lokale Beta", symbol: "cpu.fill", tint: .indigo)
            }

            VStack(alignment: .leading, spacing: 10) {
                betaRow("Chat und Sprache", true)
                betaRow("Mikrofon und TTS", true)
                betaRow("Mail, Dateien und Fotos", true)
                betaRow("Kalender und Erinnerungen", true)
                betaRow("Letzte Platzhalterseiten", false)
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
            )
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private var generalSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Allgemein", subtitle: "Grundverhalten der App.")

            VStack(alignment: .leading, spacing: 10) {
                Text("Sprache")
                    .font(.headline)
                Picker("Sprache", selection: $appState.language) {
                    Text("Deutsch").tag("Deutsch")
                    Text("English").tag("English")
                }
                .pickerStyle(.segmented)

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 6) {
                    Text("Stadt (für die Wetter-Karte)")
                        .font(.headline)
                    Text("Wird einmalig in Koordinaten umgerechnet (Open-Meteo Geocoding) - nicht bei jeder Wetterabfrage erneut.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    HStack {
                        TextField("z. B. Berlin", text: $weatherCityDraft, onCommit: submitWeatherCity)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 260)
                        Button("Übernehmen") { submitWeatherCity() }
                            .disabled(weatherCityDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    if let location = appState.weatherLocation {
                        Label("Aufgelöst: \(location.resolvedName)", systemImage: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                    if let error = appState.weatherCityError {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }

                Divider().opacity(0.4)

                Toggle(isOn: $appState.fastVoiceMode) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Schneller Sprachmodus")
                            .font(.headline)
                        Text("Kürzere Antworten, Streaming bevorzugt und weniger Denkpause. Jarvis trinkt dabei keinen Kaffee, wirkt aber so.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: appState.fastVoiceMode) { _, _ in
                    Task { await appState.saveFastVoiceModeToCore() }
                }

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Gesprächsmodus")
                        .font(.headline)
                    Text(voiceModeDescription(appState.voiceMode))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Picker("Gesprächsmodus", selection: $appState.voiceMode) {
                        ForEach(appState.availableVoiceModes, id: \.self) { mode in
                            Text(voiceModeLabel(mode)).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
                .onChange(of: appState.voiceMode) { _, newValue in
                    Task { await appState.setVoiceMode(newValue) }
                }

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Humor-Level")
                        .font(.headline)
                    Text("Wie ausgeprägt Jarvis' trocken-sarkastischer Humor ist, à la TARS aus Interstellar - 0 schaltet ihn praktisch ab, 100 sucht aktiv nach Gelegenheiten für einen Seitenhieb.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        SignalSlider(
                            value: $appState.humorLevel,
                            onEditingChanged: { editing in
                                if !editing {
                                    Task { await appState.savePersonalitySettingsToCore() }
                                }
                            }
                        )
                        Text("\(appState.humorLevel)")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 32, alignment: .trailing)
                    }
                }

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Ehrlichkeits-Level")
                        .font(.headline)
                    Text("Wie ungeschönt Jarvis unangenehme Wahrheiten oder Kritik formuliert - niedrig heißt vorsichtiger/diplomatischer, hoch heißt direkt und ohne Polster.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        SignalSlider(
                            value: $appState.honestyLevel,
                            onEditingChanged: { editing in
                                if !editing {
                                    Task { await appState.savePersonalitySettingsToCore() }
                                }
                            }
                        )
                        Text("\(appState.honestyLevel)")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 32, alignment: .trailing)
                    }
                }

                Divider().opacity(0.4)

                Toggle(isOn: $appState.alwaysListenEnabled) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Immer-Zuhör-Modus (\"Hey Jarvis\")")
                            .font(.headline)
                        Text("Jarvis lauscht dauerhaft auf dein Aktivierungswort - komplett lokal, ohne Cloud-Dienst. Push-to-Talk bleibt parallel nutzbar.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: appState.alwaysListenEnabled) { _, _ in
                    Task { await appState.applyAlwaysListenChange() }
                }

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Sprecher-Verifikation")
                        .font(.headline)
                    Text("Prüft beim Weckwort, ob wirklich Ihre Stimme spricht - wie bei Siri. Erkennt Jarvis eine andere Stimme, meldet er sich kurz zurück statt zu aktivieren. Läuft komplett lokal, keine Cloud-Anfrage.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    if appState.isEnrollingVoiceProfile {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text(voiceEnrollmentPrompt)
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        HStack(spacing: 10) {
                            Button {
                                Task { await runVoiceEnrollment() }
                            } label: {
                                Label(
                                    appState.voiceProfileEnrolled ? "Stimme neu einlernen" : "Meine Stimme einlernen",
                                    systemImage: "waveform"
                                )
                            }
                            if appState.voiceProfileEnrolled {
                                Button(role: .destructive) {
                                    Task { await appState.resetVoiceProfile() }
                                } label: {
                                    Label("Stimmprofil löschen", systemImage: "trash")
                                }
                            }
                        }
                    }

                    Toggle(isOn: $appState.speakerVerificationEnabled) {
                        Text("Beim Weckwort aktivieren")
                            .font(.callout)
                    }
                    .disabled(!appState.voiceProfileEnrolled)
                    .onChange(of: appState.speakerVerificationEnabled) { _, newValue in
                        UserDefaults.standard.set(newValue, forKey: "JarvisSpeakerVerificationEnabled")
                    }
                    if !appState.voiceProfileEnrolled {
                        Text("Erst Stimme einlernen, um diesen Schalter zu aktivieren.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .task { await appState.refreshVoiceProfileStatus() }

                Divider().opacity(0.4)

                Toggle(isOn: $appState.storeConversationEnabled) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Gesprächsverlauf speichern")
                            .font(.headline)
                        Text("Speichert die letzten Nachrichten lokal, damit der Verlauf-Tab etwas anzeigen kann. Standardmäßig aus.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: appState.storeConversationEnabled) { _, newValue in
                    Task { await appState.setStoreConversationEnabled(newValue) }
                }

                Divider().opacity(0.4)

                VStack(alignment: .leading, spacing: 6) {
                    Text("Tägliche Nutzungsanzeige")
                        .font(.headline)
                    Text("Rein informativ: zeigt dir, wie viel Zeit du heute im Gespräch mit Jarvis verbracht hast. Kein Vergleichswert ist voreingestellt - trag optional einen eigenen ein, wenn dir das hilft.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    HStack {
                        TextField("z. B. 30", text: $usageGoalDraft, onCommit: submitUsageGoal)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 100)
                        Text("Minuten")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                        Button("Übernehmen") { submitUsageGoal() }
                            .disabled(usageGoalDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if appState.dailyUsageGoalMinutes != nil {
                            Button("Zurücksetzen") {
                                usageGoalDraft = ""
                                appState.updateDailyUsageGoal(nil)
                            }
                        }
                    }
                }
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
            )
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private var profileSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Profil", subtitle: "Name und Anrede, damit Jarvis nicht alle Menschen konsequent Leon nennt. Charmant, aber unpraktisch.")

            VStack(alignment: .leading, spacing: 12) {
                Text("Name")
                    .font(.headline)
                TextField("Name", text: $appState.userName)
                    .textFieldStyle(.roundedBorder)

                Text("Anrede")
                    .font(.headline)
                Picker("Anrede", selection: $appState.userSalutation) {
                    Text("Sir").tag("sir")
                    Text("Madam").tag("madam")
                    Text("Keine besondere Anrede").tag("none")
                }
                .pickerStyle(.segmented)

                HStack {
                    Text("Vorschau: Guten Abend, \(appState.userAddress). Wie kann ich helfen?")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button {
                        Task { await appState.saveUserProfileToCore() }
                    } label: {
                        Label("Profil speichern", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
            )
        }
        .liquidGlassPanel(tint: .blue)
    }

    private var designSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Design", subtitle: "Ansicht und Farbthema lassen sich unabhängig voneinander wählen.")

            VStack(alignment: .leading, spacing: 8) {
                Text("Ansicht")
                    .font(.headline)
                Text("Dashboard ist eine komplett eigenständige Ansicht (Seitenleiste + Karten-Raster) mit fester warm-oranger Farbgebung - das Farbthema unten gilt nur für die klassische Ansicht.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Picker("Ansicht", selection: $dashboardLayoutEnabled) {
                    Text("Klassisch").tag(false)
                    Text("Dashboard").tag(true)
                }
                .pickerStyle(.segmented)
            }

            Divider().opacity(0.4)

            Text("Farbthema")
                .font(.headline)
            Picker("Design", selection: $activeThemeRaw) {
                // `.dashboard` is intentionally excluded: it is not a selectable classic-shell
                // theme, it is applied only as an environment override inside DashboardView.
                ForEach(JarvisTheme.allCases.filter { $0 != .dashboard }) { themeOption in
                    Text(themeOption.title).tag(themeOption.rawValue)
                }
            }
            .pickerStyle(.segmented)
            .disabled(dashboardLayoutEnabled)
            .opacity(dashboardLayoutEnabled ? 0.5 : 1.0)

            HStack(alignment: .center, spacing: 14) {
                if theme.isFuturistic {
                    JarvisGlowOrb(state: appState.voiceState, size: 86)
                } else {
                    JarvisVoiceOrb(state: appState.voiceState, size: 86)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(currentTheme.title)
                        .font(.headline)
                    Text(currentTheme.subtitle)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                JarvisStatusPill(
                    title: currentTheme == .futuristicBlue ? "Vision aktiv" : "Standard aktiv",
                    symbol: currentTheme == .futuristicBlue ? "sparkles" : "checkmark.circle",
                    tint: currentTheme == .futuristicBlue ? .cyan : .green
                )
            }
            .padding(14)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(theme.isDark ? theme.primaryAccent.opacity(0.36) : Color.white.opacity(0.16), lineWidth: 1)
            )
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private var voiceSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Stimme", subtitle: "Kostenlose Edge-TTS-Stimmen, live verglichen und ausgewählt - kein API-Schlüssel nötig.")

            Picker("Stimme", selection: $appState.selectedVoice) {
                ForEach(JarvisVoiceOption.allCases) { option in
                    Text(option.title).tag(option.rawValue)
                }
            }
            .pickerStyle(.segmented)
            .onChange(of: appState.selectedVoice) { _, _ in
                Task { await appState.saveSelectedVoiceToCore() }
            }
        }
        .liquidGlassPanel(tint: .cyan)
    }

    private var openAISection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("OpenAI", subtitle: "Optionaler Cloud-Modus. Der Key landet in der macOS-Keychain, nicht in Klartextdateien.")

            HStack(spacing: 12) {
                Image(systemName: appState.modelStatus.openAIKeyPresent ? "key.fill" : "key.slash.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(appState.modelStatus.openAIKeyPresent ? .green : .orange)
                    .frame(width: 40, height: 40)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

                VStack(alignment: .leading, spacing: 3) {
                    Text(appState.modelStatus.openAIKeyPresent ? "API-Key ist gespeichert" : "Kein API-Key gespeichert")
                        .font(.headline)
                    Text("Jarvis zeigt den Key nie an und schreibt ihn nicht in Logs.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            SecureField("API-Key", text: $apiKey)
                .textFieldStyle(.plain)
                .padding(13)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
                )

            HStack(spacing: 10) {
                Button {
                    Task {
                        // Only clear the field on success - it previously cleared
                        // unconditionally, so a failed save (e.g. Keychain locked) silently
                        // discarded the key the user just typed while the UI looked as if
                        // it had worked.
                        do {
                            try await appState.serverController.setOpenAIKey(apiKey)
                            apiKey = ""
                        } catch {
                            // Keep the typed key in the field so the user can retry.
                        }
                        await appState.refreshStatus()
                    }
                } label: {
                    Label("In Keychain speichern", systemImage: "key.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Button(role: .destructive) {
                    Task {
                        try? await appState.serverController.deleteOpenAIKey()
                        await appState.refreshStatus()
                    }
                } label: {
                    Label("API-Key löschen", systemImage: "trash")
                }
                .buttonStyle(.bordered)
            }
        }
        .liquidGlassPanel(tint: .orange)
    }

    private var coreSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Lokaler Jarvis-Core", subtitle: "Verbindung zum Python-Core und lokalen Modell.")

            HStack(spacing: 12) {
                statusBadge(
                    title: "Verbindung",
                    value: appState.serverController.isRunning ? "Verbunden" : "Nicht verbunden",
                    symbol: appState.serverController.isRunning ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                    tint: appState.serverController.isRunning ? .green : .orange
                )
                statusBadge(
                    title: "Modell",
                    value: appState.modelStatus.activeModel,
                    symbol: "cpu.fill",
                    tint: .indigo
                )
            }

            HStack(spacing: 10) {
                Button {
                    Task { await appState.ensureServerConnected() }
                } label: {
                    Label("Verbindung neu aufbauen", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.borderedProminent)

                Button {
                    Task {
                        await appState.serverController.stop()
                        await appState.ensureServerConnected()
                    }
                } label: {
                    Label("Core neu starten", systemImage: "power")
                }
                .buttonStyle(.bordered)
            }
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private var licensesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Lizenzen", subtitle: "Die lokalen KI-Modelle (phi4-mini, gemma3:4b, qwen3:4b) stehen unter eigenen Lizenzbedingungen der jeweiligen Hersteller.")

            Button {
                appState.selectedSection = .licenses
            } label: {
                Label("Lizenzen ansehen", systemImage: "doc.text.magnifyingglass")
            }
            .buttonStyle(.bordered)
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private func statusBadge(title: String, value: String, symbol: String, tint: Color) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
                .frame(width: 32, height: 32)
                .background(.thinMaterial, in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
        )
    }

    private func submitWeatherCity() {
        Task { await appState.updateWeatherCity(weatherCityDraft) }
    }

    private func submitUsageGoal() {
        let trimmed = usageGoalDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let value = Double(trimmed), value > 0 else { return }
        appState.updateDailyUsageGoal(value)
    }

    private func runVoiceEnrollment() async {
        voiceEnrollmentPrompt = "Vorbereitung ..."
        await appState.enrollVoiceProfile { index, total in
            voiceEnrollmentPrompt = "Sag ein paar Worte, Satz \(index + 1) von \(total) ..."
        }
        voiceEnrollmentPrompt = ""
    }

    private func voiceModeLabel(_ mode: String) -> String {
        switch mode {
        case "kurz": return "Kurz"
        case "fokus": return "Fokus"
        case "diskret": return "Diskret"
        case "privat": return "Privat"
        default: return "Standard"
        }
    }

    private func voiceModeDescription(_ mode: String) -> String {
        switch mode {
        case "kurz":
            return "Extrem knappe Antworten, meist ein Satz."
        case "fokus":
            return "Ausführliche, technische Antworten - für Programmierung und Planung."
        case "diskret":
            return "Nur Text, keine Sprachausgabe."
        case "privat":
            return "Keine Websuche, keine externen Datenquellen für diese Unterhaltung."
        default:
            return "Normale, ausgewogene Antworten."
        }
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

    private func betaRow(_ title: String, _ ready: Bool) -> some View {
        HStack(spacing: 10) {
            Image(systemName: ready ? "checkmark.circle.fill" : "clock.badge.exclamationmark")
                .foregroundStyle(ready ? .green : .orange)
            Text(title)
                .font(.callout)
            Spacer()
            Text(ready ? "bereit" : "folgt")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
    }

    private var currentTheme: JarvisTheme {
        JarvisTheme(rawValue: activeThemeRaw) ?? .classic
    }
}
