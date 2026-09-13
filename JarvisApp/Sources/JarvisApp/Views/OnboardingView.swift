import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @State private var step = 0
    @State private var tappedExamples: Set<String> = []

    private let capabilityItems: [(icon: String, title: String, detail: String)] = [
        ("envelope", "Mail", "Zusammenfassen, durchsuchen, beantworten"),
        ("calendar", "Kalender", "Termine lesen und anlegen"),
        ("folder", "Dateien", "Lokal suchen, öffnen, verschieben"),
        ("music.note", "Musik", "Wiedergabe über Apple Music steuern"),
        ("ear", "Immer-Zuhören-Modus", "Optional per Aktivierungswort"),
        ("cpu", "OpenClaw", "Läuft auf deinem Mac Mini, immer erreichbar")
    ]

    private let examples = [
        "Wie wird heute das Wetter?",
        "Erstelle morgen um 18 Uhr eine Erinnerung.",
        "Lies meine heutigen Termine.",
        "Öffne meine Mails.",
        "Suche nach Informationen über Apple.",
        "Fasse diese Datei zusammen.",
        "Erstelle einen Kalendereintrag."
    ]

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            content
                .frame(maxWidth: 760)
                .liquidGlassPanel(tint: .cyan, cornerRadius: 32)
            HStack {
                if step > 0 {
                    Button("Zurück") { withAnimation { step -= 1 } }
                }
                Spacer()
                Button(step == 5 ? "Jarvis starten" : "Weiter") {
                    withAnimation {
                        if step == 5 {
                            Task {
                                await appState.saveUserProfileToCore()
                                appState.completeOnboarding()
                            }
                        } else {
                            step += 1
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .frame(maxWidth: 760)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
        .background(LiquidGlassBackground())
    }

    @ViewBuilder private var content: some View {
        switch step {
        case 0: welcome
        case 1: capabilities
        case 2: language
        case 3: profile
        case 4: privacy
        case 5: tutorial
        default: done
        }
    }

    private var welcome: some View {
        VStack(spacing: 18) {
            Image(systemName: "sparkles.rectangle.stack")
                .font(.system(size: 58))
                .foregroundStyle(theme.isDark ? theme.primaryAccent : .blue)
            Text("Willkommen bei Jarvis.")
                .font(.largeTitle.bold())
            Text("Dein lokaler KI-Assistent für macOS. Datenschutz zuerst, lokal bevorzugt und Cloud nur optional.")
                .font(.title3)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            if appState.bootstrapStatus != nil {
                SetupProgressCard()
            }
        }
    }

    private var capabilities: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Das kann Jarvis")
                .font(.largeTitle.bold())
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], spacing: 12) {
                ForEach(capabilityItems, id: \.title) { item in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: item.icon)
                            .font(.title3)
                            .foregroundStyle(theme.isDark ? theme.primaryAccent : .blue)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title)
                                .font(.subheadline.weight(.semibold))
                            Text(item.detail)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
                    )
                }
            }
        }
    }

    private var language: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Sprache auswählen")
                .font(.largeTitle.bold())
            Picker("Sprache", selection: $appState.language) {
                Text("Deutsch").tag("Deutsch")
                Text("English").tag("English")
            }
            .pickerStyle(.segmented)
        }
    }

    private var profile: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Wie soll Jarvis dich ansprechen?")
                .font(.largeTitle.bold())
            Text("Der Name wird lokal gespeichert und hilft Jarvis, natürlicher zu antworten. Keine kleine Sache, außer man mag generische Assistenten. Niemand mag generische Assistenten.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            TextField("Dein Name", text: $appState.userName)
                .textFieldStyle(.roundedBorder)
                .font(.title3)

            Picker("Anrede", selection: $appState.userSalutation) {
                Text("Sir").tag("sir")
                Text("Madam").tag("madam")
                Text("Keine besondere Anrede").tag("none")
            }
            .pickerStyle(.radioGroup)

            Text(previewText)
                .font(.headline)
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
    }

    private var previewText: String {
        switch appState.userSalutation {
        case "madam":
            return "Beispiel: Guten Abend, Madam. Wie kann ich helfen?"
        case "none":
            let name = appState.displayUserName
            return "Beispiel: Guten Abend, \(name). Wie kann ich helfen?"
        default:
            return "Beispiel: Guten Abend, Sir. Wie kann ich helfen?"
        }
    }

    private var privacy: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Datenschutz")
                .font(.largeTitle.bold())
            Label("Jarvis läuft über OpenClaw auf deinem eigenen Mac Mini, nicht in einer fremden Cloud.", systemImage: "lock")
            Label("Mail, Kalender, Fotos und Dateien koppelst du einzeln in den Einstellungen - erst dann greift Jarvis darauf zu.", systemImage: "link")
            Label("Mikrofon und Spracherkennung kannst du jederzeit unter „Datenschutz“ prüfen und ändern.", systemImage: "switch.2")
        }
        .font(.title3)
    }

    private var tutorial: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Jarvis kennenlernen")
                .font(.largeTitle.bold())
            Text("Nur ein paar Beispiele, was du später fragen kannst - zum Ausprobieren geht es mit \"Jarvis starten\" los.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 230))], spacing: 12) {
                ForEach(examples, id: \.self) { example in
                    Button {
                        withAnimation { _ = tappedExamples.insert(example) }
                    } label: {
                        Label(example, systemImage: tappedExamples.contains(example) ? "checkmark.circle.fill" : "circle")
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
    }

    private var done: some View {
        VStack(spacing: 18) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 70))
                .foregroundStyle(.green)
                .symbolEffect(.bounce, value: step)
            Text("Jarvis ist einsatzbereit.")
                .font(.largeTitle.bold())
            Text("Lokal, kontrolliert und bereit für alles, was ein Computer ausnahmsweise sinnvoll erledigt.")
                .foregroundStyle(.secondary)
        }
    }
}
