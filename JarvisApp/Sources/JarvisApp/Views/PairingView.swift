import SwiftUI

/// Kopplungs-Bildschirm für OpenClaw (Phase 1, "JarvisApp auf OpenClaw umstellen"-Plan,
/// 2026-09-08) - Port von JarvisMobile's PairingView.swift, angepasst an JarvisApp's
/// eigene Optik (liquidGlassPanel). Ersetzt den alten Lokal/Fernbetrieb-Umschalter in
/// SettingsView.swift: JarvisApp spricht ab jetzt immer nur mit OpenClaw auf dem Mac
/// Mini, kein lokaler Modus mehr.
struct PairingView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage(OpenClawSettings.hostKey) private var host = ""
    @State private var tokenDraft = ""
    @State private var tokenSaved = OpenClawSettings.token != nil
    @State private var testResult: (ok: Bool, message: String)?
    @State private var isTesting = false
    @State private var ttsTokenDraft = ""
    @State private var ttsTokenSaved = OpenClawSettings.ttsToken != nil
    @State private var filesTokenDraft = ""
    @State private var filesTokenSaved = OpenClawSettings.filesToken != nil
    @State private var photosTokenDraft = ""
    @State private var photosTokenSaved = OpenClawSettings.photosToken != nil
    @State private var memoryTokenDraft = ""
    @State private var memoryTokenSaved = OpenClawSettings.memoryToken != nil
    @State private var gatewayActivityTokenDraft = ""
    @State private var gatewayActivityTokenSaved = OpenClawSettings.gatewayActivityToken != nil
    @State private var remoteTokenDraft = ""
    @State private var remoteTokenSaved = RemoteConnectionSettings.token != nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                sectionHeader(
                    "Verbindung zu OpenClaw",
                    subtitle: "Verbindet diesen Mac mit dem 24/7 laufenden Jarvis-Server (OpenClaw auf dem Mac Mini), erreichbar über Tailscale."
                )

                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Mac-Mini-Adresse")
                            .font(.headline)
                        Text("Tailscale-IP oder MagicDNS-Name, ohne \"http://\" und ohne Port.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                        TextField("z. B. 100.115.128.74", text: $host)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Token")
                            .font(.headline)
                        Text(tokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert.")
                            .font(.callout)
                            .foregroundStyle(tokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal auslesen: openclaw config get gateway.auth.token")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Token vom Mac Mini", text: $tokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.token = tokenDraft
                                tokenDraft = ""
                                tokenSaved = OpenClawSettings.token != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(tokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if tokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.token = nil
                                    tokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Sprachausgabe-Server (Edge-TTS)")
                            .font(.headline)
                        Text(ttsTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert - Apple-Stimme wird solange als Ersatz benutzt.")
                            .font(.callout)
                            .foregroundStyle(ttsTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/tts_proxy_server.py läuft.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("TTS-Proxy-Token vom Mac Mini", text: $ttsTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.ttsToken = ttsTokenDraft
                                ttsTokenDraft = ""
                                ttsTokenSaved = OpenClawSettings.ttsToken != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(ttsTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if ttsTokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.ttsToken = nil
                                    ttsTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Alter Backend (Fernbetrieb)")
                            .font(.headline)
                        Text(remoteTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Ohne Token bleiben noch nicht migrierte Bereiche (Mail, Kalender, Fotos, Modell-Download) auf diesem Mac unerreichbar, solange JarvisApp nicht auf dem Mac Mini selbst laeuft.")
                            .font(.callout)
                            .foregroundStyle(remoteTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini in der Datei local_server.token im Projektordner zu finden (alter Backend, nicht OpenClaw).")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Fernbetrieb-Token vom Mac Mini", text: $remoteTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                RemoteConnectionSettings.token = remoteTokenDraft
                                remoteTokenDraft = ""
                                remoteTokenSaved = RemoteConnectionSettings.token != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(remoteTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if remoteTokenSaved {
                                Button(role: .destructive) {
                                    RemoteConnectionSettings.token = nil
                                    remoteTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Datei-Proxy")
                            .font(.headline)
                        Text(filesTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert - Dateisuche in JarvisApp bleibt solange offline.")
                            .font(.callout)
                            .foregroundStyle(filesTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/files_proxy_server.py läuft.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Datei-Proxy-Token vom Mac Mini", text: $filesTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.filesToken = filesTokenDraft
                                filesTokenDraft = ""
                                filesTokenSaved = OpenClawSettings.filesToken != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(filesTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if filesTokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.filesToken = nil
                                    filesTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Fotos-Proxy")
                            .font(.headline)
                        Text(photosTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert - Fotos-Fachbereich bleibt solange offline.")
                            .font(.callout)
                            .foregroundStyle(photosTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/photos_proxy_server.py läuft.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Fotos-Proxy-Token vom Mac Mini", text: $photosTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.photosToken = photosTokenDraft
                                photosTokenDraft = ""
                                photosTokenSaved = OpenClawSettings.photosToken != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(photosTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if photosTokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.photosToken = nil
                                    photosTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Gedächtnis-Proxy")
                            .font(.headline)
                        Text(memoryTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert - Gedächtnis-Ansicht bleibt solange offline.")
                            .font(.callout)
                            .foregroundStyle(memoryTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/memory_proxy_server.py läuft.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Gedächtnis-Proxy-Token vom Mac Mini", text: $memoryTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.memoryToken = memoryTokenDraft
                                memoryTokenDraft = ""
                                memoryTokenSaved = OpenClawSettings.memoryToken != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(memoryTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if memoryTokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.memoryToken = nil
                                    memoryTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Gateway-Aktivitäts-Proxy")
                            .font(.headline)
                        Text(gatewayActivityTokenSaved ? "Token ist in der macOS-Keychain gespeichert." : "Noch kein Token gespeichert - Live-Status während Jarvis arbeitet bleibt solange aus.")
                            .font(.callout)
                            .foregroundStyle(gatewayActivityTokenSaved ? Color.secondary : Color.orange)
                        Text("Auf dem Mac Mini im Terminal ausgegeben, sobald scripts/gateway_activity_proxy.mjs läuft.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        SecureField("Gateway-Aktivitäts-Proxy-Token vom Mac Mini", text: $gatewayActivityTokenDraft)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 320)

                        HStack(spacing: 10) {
                            Button("Token speichern") {
                                OpenClawSettings.gatewayActivityToken = gatewayActivityTokenDraft
                                gatewayActivityTokenDraft = ""
                                gatewayActivityTokenSaved = OpenClawSettings.gatewayActivityToken != nil
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(gatewayActivityTokenDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            if gatewayActivityTokenSaved {
                                Button(role: .destructive) {
                                    OpenClawSettings.gatewayActivityToken = nil
                                    gatewayActivityTokenSaved = false
                                } label: {
                                    Label("Token löschen", systemImage: "trash")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    Divider().opacity(0.4)

                    HStack(spacing: 10) {
                        Button {
                            Task { await testConnection() }
                        } label: {
                            if isTesting {
                                ProgressView()
                            } else {
                                Label("Verbindung testen", systemImage: "network")
                            }
                        }
                        .buttonStyle(.bordered)
                        .disabled(isTesting)

                        if let testResult {
                            Label(testResult.message, systemImage: testResult.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                .font(.callout)
                                .foregroundStyle(testResult.ok ? .green : .orange)
                        }
                    }
                }
                .liquidGlassPanel(tint: .indigo)
            }
            .padding(28)
            .frame(maxWidth: 920, alignment: .leading)
        }
        .navigationTitle("Verbindung")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Fertig") { dismiss() }
            }
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

    private func testConnection() async {
        isTesting = true
        defer { isTesting = false }
        do {
            let health = try await OpenClawClient().health()
            testResult = (true, "Verbunden: OpenClaw Gateway (\(health.status))")
        } catch {
            testResult = (false, error.localizedDescription)
        }
    }
}

#Preview {
    PairingView()
}
