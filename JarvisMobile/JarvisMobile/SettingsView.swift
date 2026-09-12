import SwiftUI
import AVFoundation

/// Persona controls, ported from JarvisApp's SettingsView (macOS) - Humor-
/// /Ehrlichkeits-Level. Unlike the old app, there is no local config.json to
/// write to anymore: this app has no backend of its own, only a Gateway
/// client. Instead, changing a slider sends Jarvis an explicit instruction
/// over the normal chat completions endpoint and lets the AGENT ITSELF
/// update its own SOUL.md (it already has file-write tools) - the OpenClaw-
/// idiomatic way to change persona, matching how a user would ask for this
/// verbally in the first place.
struct SettingsView: View {
    @EnvironmentObject private var locationManager: LocationManager
    @AppStorage("JarvisHumorLevel") private var humorLevel = 60.0
    @AppStorage("JarvisHonestyLevel") private var honestyLevel = 70.0
    @State private var isApplying = false
    @State private var lastAppliedMessage: String?
    @State private var errorMessage: String?
    @AppStorage(VoiceManager.selectedVoiceIdentifierKey) private var selectedVoiceIdentifier = ""
    @AppStorage(VoiceManager.wakeListeningEnabledKey) private var wakeListeningEnabled = false
    private let synthesizer = AVSpeechSynthesizer()

    private var germanVoices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix("de") }
            .sorted { $0.quality.rawValue > $1.quality.rawValue }
    }

    private func qualityLabel(_ quality: AVSpeechSynthesisVoiceQuality) -> String {
        switch quality {
        case .premium: return "Premium"
        case .enhanced: return "Enhanced"
        default: return "Standard"
        }
    }

    var body: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Humor-Level")
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("Wie ausgeprägt Jarvis' trocken-sarkastischer Humor ist - 0 schaltet ihn praktisch ab, 100 sucht aktiv nach Gelegenheiten für einen Seitenhieb.")
                        .font(.callout)
                        .foregroundStyle(JarvisTheme.textSecondary)
                    HStack {
                        Slider(value: $humorLevel, in: 0...100, step: 1) { editing in
                            if !editing { Task { await applyPersonality() } }
                        }
                        .tint(JarvisTheme.accent)
                        Text("\(Int(humorLevel))")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(JarvisTheme.textSecondary)
                            .frame(width: 32, alignment: .trailing)
                    }
                }
                .padding(.vertical, 4)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Ehrlichkeits-Level")
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("Wie ungeschönt Jarvis unangenehme Wahrheiten oder Kritik formuliert - niedrig heißt vorsichtiger/diplomatischer, hoch heißt direkt und ohne Polster.")
                        .font(.callout)
                        .foregroundStyle(JarvisTheme.textSecondary)
                    HStack {
                        Slider(value: $honestyLevel, in: 0...100, step: 1) { editing in
                            if !editing { Task { await applyPersonality() } }
                        }
                        .tint(JarvisTheme.accent)
                        Text("\(Int(honestyLevel))")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(JarvisTheme.textSecondary)
                            .frame(width: 32, alignment: .trailing)
                    }
                }
                .padding(.vertical, 4)
            } header: {
                Text("Persönlichkeit")
            } footer: {
                if isApplying {
                    Label("Jarvis passt seine Persönlichkeit an...", systemImage: "hourglass")
                        .foregroundStyle(JarvisTheme.textSecondary)
                } else if let lastAppliedMessage {
                    Label(lastAppliedMessage, systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else if let errorMessage {
                    Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
            }
            .listRowBackground(JarvisTheme.cardFill)

            Section {
                ForEach(germanVoices, id: \.identifier) { voice in
                    HStack {
                        Image(systemName: selectedVoiceIdentifier == voice.identifier ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(selectedVoiceIdentifier == voice.identifier ? JarvisTheme.accent : JarvisTheme.textSecondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(voice.name)
                                .foregroundStyle(.white)
                            Text(qualityLabel(voice.quality))
                                .font(.caption)
                                .foregroundStyle(voice.quality == .default ? JarvisTheme.textSecondary : JarvisTheme.accent)
                        }
                        Spacer()
                        Button {
                            let utterance = AVSpeechUtterance(string: "Hallo, ich bin Jarvis. So klinge ich mit dieser Stimme.")
                            utterance.voice = voice
                            synthesizer.speak(utterance)
                        } label: {
                            Image(systemName: "play.circle.fill")
                                .font(.title2)
                                .foregroundStyle(JarvisTheme.accent)
                        }
                        .buttonStyle(.plain)
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { selectedVoiceIdentifier = voice.identifier }
                }
                if !selectedVoiceIdentifier.isEmpty {
                    Button("Automatische Auswahl (beste Qualität)") {
                        selectedVoiceIdentifier = ""
                    }
                    .foregroundStyle(JarvisTheme.accent)
                }
                if germanVoices.allSatisfy({ $0.quality == .default }) {
                    Text("Nur Standard-Qualität installiert. Für bessere Stimmen: Einstellungen → Bedienungshilfen → Gesprochener Inhalt → Stimmen → Deutsch → eine Enhanced/Premium-Stimme herunterladen.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            } header: {
                Text("Sprachausgabe")
            } footer: {
                Text("▶ tippen zum Anhören, Zeile tippen zum Auswählen. Ohne Auswahl nimmt Jarvis automatisch die beste verfügbare Qualität.")
            }
            .listRowBackground(JarvisTheme.cardFill)

            Section {
                Toggle(isOn: $wakeListeningEnabled) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("„Hey Jarvis\" Aktivierungswort")
                            .foregroundStyle(.white)
                        Text("Jarvis hört im Hintergrund mit, solange die App nicht vollständig beendet wird - sag einfach seinen Namen. Nach einer Antwort hört er automatisch weiter zu, bis du z. B. „Danke Jarvis, das passt\" sagst.")
                            .font(.caption)
                            .foregroundStyle(JarvisTheme.textSecondary)
                    }
                }
                .tint(JarvisTheme.accent)
            } header: {
                Text("Sprachaktivierung")
            }
            .listRowBackground(JarvisTheme.cardFill)

            Section {
                Text("Läuft jetzt über OpenClaw: Kalender, Mail, Kontakte, Notizen, Erinnerungen, Kamera und Screenshots sind als Skills direkt bei Jarvis eingerichtet - keine separate Konfiguration hier nötig, frag ihn einfach im Chat danach.")
                    .font(.callout)
                    .foregroundStyle(JarvisTheme.textSecondary)
            } header: {
                Text("Fähigkeiten")
            }
            .listRowBackground(JarvisTheme.cardFill)

            Section {
                Text("Jarvis erkennt per GPS, wenn du zu Hause ankommst, und begrüßt dich über den Mac Mini - komplett lokal, kein Standort-Tracking-Dienst. Tipp diesen Button EINMAL an, während du wirklich zu Hause bist.")
                    .font(.callout)
                    .foregroundStyle(JarvisTheme.textSecondary)

                if locationManager.authorizationStatus != .authorizedAlways {
                    Button("Standortzugriff (\"Immer\") anfragen") {
                        locationManager.requestAuthorization()
                    }
                }

                Button("Aktuellen Standort als Zuhause speichern") {
                    locationManager.setCurrentLocationAsHome()
                }

                if locationManager.homeSet {
                    Label("Zuhause ist gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Button("Zuhause löschen", role: .destructive) {
                        locationManager.clearHome()
                    }
                } else {
                    Label("Noch kein Zuhause gespeichert.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }

                if let lastError = locationManager.lastError {
                    Label(lastError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .font(.callout)
                }
            } header: {
                Text("Ankunfts-Begrüßung")
            }
            .listRowBackground(JarvisTheme.cardFill)
        }
        .scrollContentBackground(.hidden)
        .background(JarvisBackground())
        .navigationTitle("Einstellungen")
    }

    private func applyPersonality() async {
        isApplying = true
        errorMessage = nil
        lastAppliedMessage = nil
        defer { isApplying = false }

        let instruction = """
        Bitte aktualisiere deine eigene SOUL.md mit diesen beiden Persönlichkeits-Reglern - überschreibe frühere Humor-/Ehrlichkeits-Angaben dort, statt sie zu duplizieren:
        - Humor-Level: \(Int(humorLevel))/100 (0 = kein Humor, sachlich; 100 = sucht aktiv nach Gelegenheiten für trocken-sarkastische Seitenhiebe, à la TARS aus Interstellar)
        - Ehrlichkeits-Level: \(Int(honestyLevel))/100 (0 = vorsichtig/diplomatisch bei unangenehmen Wahrheiten; 100 = direkt und ungeschönt, ohne Polster)
        Bestätige kurz in einem Satz, dass du das gespeichert hast.
        """

        do {
            let response = try await APIClient().sendChat(instruction, history: [])
            lastAppliedMessage = response.answer
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

#Preview {
    NavigationStack { SettingsView() }
}
