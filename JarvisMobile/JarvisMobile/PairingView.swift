import SwiftUI

struct PairingView: View {
    @AppStorage(RemoteSettings.hostKey) private var host = ""
    @State private var tokenDraft = ""
    @State private var tokenSaved = RemoteSettings.token != nil
    @State private var testResult: (ok: Bool, message: String)?
    @State private var isTesting = false
    @State private var ttsTokenDraft = ""
    @State private var ttsTokenSaved = RemoteSettings.ttsToken != nil
    @State private var memoryTokenDraft = ""
    @State private var memoryTokenSaved = RemoteSettings.memoryToken != nil
    @State private var gatewayActivityTokenDraft = ""
    @State private var gatewayActivityTokenSaved = RemoteSettings.gatewayActivityToken != nil
    @State private var healthTokenDraft = ""
    @State private var healthTokenSaved = RemoteSettings.healthToken != nil

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

            Section("Gedächtnis-Proxy") {
                if memoryTokenSaved {
                    Label("Token ist in der Keychain gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Noch kein Token gespeichert - Speicher-Ansicht bleibt solange offline.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/memory_proxy_server.py läuft.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SecureField("Gedächtnis-Proxy-Token vom Mac Mini", text: $memoryTokenDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Token speichern") {
                    RemoteSettings.memoryToken = memoryTokenDraft
                    memoryTokenDraft = ""
                    memoryTokenSaved = RemoteSettings.memoryToken != nil
                }
                .disabled(memoryTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if memoryTokenSaved {
                    Button("Token löschen", role: .destructive) {
                        RemoteSettings.memoryToken = nil
                        memoryTokenSaved = false
                    }
                }
            }

            Section("Gateway-Aktivitäts-Proxy") {
                if gatewayActivityTokenSaved {
                    Label("Token ist in der Keychain gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Noch kein Token gespeichert - Live-Status während Jarvis arbeitet bleibt solange aus.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/gateway_activity_proxy.mjs läuft.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SecureField("Gateway-Aktivitäts-Proxy-Token vom Mac Mini", text: $gatewayActivityTokenDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Token speichern") {
                    RemoteSettings.gatewayActivityToken = gatewayActivityTokenDraft
                    gatewayActivityTokenDraft = ""
                    gatewayActivityTokenSaved = RemoteSettings.gatewayActivityToken != nil
                }
                .disabled(gatewayActivityTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if gatewayActivityTokenSaved {
                    Button("Token löschen", role: .destructive) {
                        RemoteSettings.gatewayActivityToken = nil
                        gatewayActivityTokenSaved = false
                    }
                }
            }

            Section("Gesundheits-Proxy") {
                if healthTokenSaved {
                    Label("Token ist in der Keychain gespeichert.", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Label("Noch kein Token gespeichert - Gesundheitswerte werden solange nicht hochgeladen.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/health_proxy_server.py läuft.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                SecureField("Gesundheits-Proxy-Token vom Mac Mini", text: $healthTokenDraft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Token speichern") {
                    RemoteSettings.healthToken = healthTokenDraft
                    healthTokenDraft = ""
                    healthTokenSaved = RemoteSettings.healthToken != nil
                }
                .disabled(healthTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if healthTokenSaved {
                    Button("Token löschen", role: .destructive) {
                        RemoteSettings.healthToken = nil
                        healthTokenSaved = false
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
