import SwiftUI
import AVFoundation
import Speech
import AppKit

/// Datenschutz-/Berechtigungs-Uebersicht, verschlankt auf echten macOS-TCC-Status
/// (Rest-Migrations-Plan, Abschnitt 3). Die alte Version zeigte 16 Consent-Schalter
/// (Mikrofon/Mail/Kalender/Kontakte/Fotos/...), die ein eigenes, ueber das alte Backend
/// verwaltetes Consent-Modell abbildeten - nicht echten macOS-Berechtigungsstatus. Seit
/// Mail/Kalender/Fotos/Dateien ueber OpenClaw-Skills auf dem Mac Mini laufen (nicht mehr
/// lokal auf diesem Mac), ist dieses alte Modell fuer die meisten Eintraege ohnehin
/// obsolet - die jeweiligen Proxy-Tokens sind der eigentliche Freischalt-Schritt (siehe
/// PhotosView.photosAllowed/FilesView.filesAllowed fuer denselben, bereits etablierten
/// Fix). Uebrig bleiben genau die zwei Berechtigungen, die JarvisApp selbst LOKAL auf
/// diesem Mac braucht: Mikrofon (Audioaufnahme) und Spracherkennung (on-device STT) -
/// beide direkt ueber Apples eigene Authorization-APIs abgefragt, kein Backend-Call mehr.
struct PrivacyView: View {
    @State private var microphoneStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    @State private var speechStatus = SFSpeechRecognizer.authorizationStatus()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionRows
            }
            .padding(28)
            .frame(maxWidth: 720, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Datenschutz")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    refreshStatus()
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .onAppear { refreshStatus() }
    }

    private func refreshStatus() {
        microphoneStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        speechStatus = SFSpeechRecognizer.authorizationStatus()
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "hand.raised.fill", tint: .green)

            VStack(alignment: .leading, spacing: 6) {
                Text("Datenschutz")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("JarvisApp selbst braucht auf diesem Mac nur Mikrofon und Spracherkennung - Mail, Kalender, Fotos und Dateien laufen über eigene, separat gekoppelte Proxys auf dem Mac Mini (siehe „Verbindung“).")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .green)
    }

    private var permissionRows: some View {
        VStack(spacing: 12) {
            permissionRow(
                title: "Mikrofon",
                symbol: "mic.fill",
                explanation: "Für Push-to-Talk und den Immer-Zuhör-Modus - Jarvis nimmt nur auf, während du sprichst oder das Aktivierungswort erkannt wurde.",
                status: authorizationLabel(microphoneStatus),
                allowed: microphoneStatus == .authorized
            ) {
                if microphoneStatus == .notDetermined {
                    AVCaptureDevice.requestAccess(for: .audio) { _ in
                        DispatchQueue.main.async { refreshStatus() }
                    }
                } else {
                    openSystemSettings()
                }
            }

            permissionRow(
                title: "Spracherkennung",
                symbol: "waveform",
                explanation: "Für die on-device Transkription deiner Sprache (Live-Diktat und Aktivierungswort-Erkennung) - läuft komplett lokal, keine Cloud-Anfrage.",
                status: authorizationLabel(speechStatus),
                allowed: speechStatus == .authorized
            ) {
                if speechStatus == .notDetermined {
                    SFSpeechRecognizer.requestAuthorization { _ in
                        DispatchQueue.main.async { refreshStatus() }
                    }
                } else {
                    openSystemSettings()
                }
            }
        }
    }

    private func permissionRow(
        title: String,
        symbol: String,
        explanation: String,
        status: String,
        allowed: Bool,
        action: @escaping () -> Void
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(allowed ? .green : .secondary)
                .frame(width: 34, height: 34)
                .background(.thinMaterial, in: Circle())
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(title)
                        .font(.headline)
                    statusPill(status: status, allowed: allowed)
                }
                Text(explanation)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 12)

            Button(allowed ? "Systemeinstellungen" : "Erlauben", action: action)
                .buttonStyle(.bordered)
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private func statusPill(status: String, allowed: Bool) -> some View {
        Text(status)
            .font(.caption.weight(.semibold))
            .foregroundStyle(allowed ? .green : .secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background((allowed ? Color.green : Color.secondary).opacity(0.12), in: Capsule())
    }

    private func authorizationLabel(_ status: AVAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "Erlaubt"
        case .denied, .restricted: return "Blockiert"
        case .notDetermined: return "Noch nicht gefragt"
        @unknown default: return "Unbekannt"
        }
    }

    private func authorizationLabel(_ status: SFSpeechRecognizerAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "Erlaubt"
        case .denied, .restricted: return "Blockiert"
        case .notDetermined: return "Noch nicht gefragt"
        @unknown default: return "Unbekannt"
        }
    }

    private func openSystemSettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy") else { return }
        NSWorkspace.shared.open(url)
    }
}
