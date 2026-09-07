import SwiftUI

struct PairingView: View {
    @AppStorage(RemoteSettings.hostKey) private var host = ""
    @State private var tokenDraft = ""
    @State private var tokenSaved = RemoteSettings.token != nil
    @State private var testResult: (ok: Bool, message: String)?
    @State private var isTesting = false
    @State private var ttsTokenDraft = ""
    @State private var ttsTokenSaved = RemoteSettings.ttsToken != nil

    var body: some View {
        Form {
            Section {
                Text("Verbindet dieses iPhone mit deinem 24/7 laufenden Jarvis-Server (dem Mac Mini), erreichbar über Tailscale. Kein eigenes Gehirn hier - nur Chat und Hinweise.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Section("Mac-Mini-Adresse") {
                TextField("z. B. 100.115.128.74", text: $host)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.asciiCapable)
            }

            Section("Token") {
                if tokenSaved {
                    Label("Token ist in der Keychain gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Noch kein Token gespeichert.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Text("Auf dem Mac Mini im Terminal auslesen: openclaw config get gateway.auth.token")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SecureField("Token vom Mac Mini", text: $tokenDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Token speichern") {
                    RemoteSettings.token = tokenDraft
                    tokenDraft = ""
                    tokenSaved = RemoteSettings.token != nil
                }
                .disabled(tokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if tokenSaved {
                    Button("Token löschen", role: .destructive) {
                        RemoteSettings.token = nil
                        tokenSaved = false
                    }
                }
            }

            Section("Sprachausgabe-Server (Edge-TTS)") {
                if ttsTokenSaved {
                    Label("Token ist in der Keychain gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Noch kein Token gespeichert - Apple-Stimme wird solange als Ersatz benutzt.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/tts_proxy_server.py läuft.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SecureField("TTS-Proxy-Token vom Mac Mini", text: $ttsTokenDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Token speichern") {
                    RemoteSettings.ttsToken = ttsTokenDraft
                    ttsTokenDraft = ""
                    ttsTokenSaved = RemoteSettings.ttsToken != nil
                }
                .disabled(ttsTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if ttsTokenSaved {
                    Button("Token löschen", role: .destructive) {
                        RemoteSettings.ttsToken = nil
                        ttsTokenSaved = false
                    }
                }
            }

            Section {
                Button {
                    Task { await testConnection() }
                } label: {
                    if isTesting {
                        ProgressView()
                    } else {
                        Text("Verbindung testen")
                    }
                }
                .disabled(isTesting)

                if let testResult {
                    Label(testResult.message, systemImage: testResult.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(testResult.ok ? .green : .orange)
                        .font(.callout)
                }
            }
        }
        .navigationTitle("Verbindung")
    }

    private func testConnection() async {
        isTesting = true
        defer { isTesting = false }
        do {
            let health = try await APIClient().health()
            testResult = (true, "Verbunden: OpenClaw Gateway (\(health.status))")
        } catch {
            testResult = (false, error.localizedDescription)
        }
    }
}

#Preview {
    NavigationStack { PairingView() }
}
