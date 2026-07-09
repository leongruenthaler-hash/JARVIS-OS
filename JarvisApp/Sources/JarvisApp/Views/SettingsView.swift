import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @AppStorage("JarvisActiveTheme") private var activeThemeRaw = JarvisTheme.classic.rawValue
    @State private var apiKey = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                betaSection
                profileSection
                generalSection
                designSection
                openAISection
                coreSection
            }
            .padding(28)
            .frame(maxWidth: 920, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Einstellungen")
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
            sectionHeader("Design", subtitle: "Wechsle zwischen der bestehenden Optik und dem neuen Jarvis-Vision-Look.")

            Picker("Design", selection: $activeThemeRaw) {
                ForEach(JarvisTheme.allCases) { themeOption in
                    Text(themeOption.title).tag(themeOption.rawValue)
                }
            }
            .pickerStyle(.segmented)

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
                    .strokeBorder(theme.isFuturistic ? theme.primaryAccent.opacity(0.36) : Color.white.opacity(0.16), lineWidth: 1)
            )
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
                        try? await appState.serverController.setOpenAIKey(apiKey)
                        apiKey = ""
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
