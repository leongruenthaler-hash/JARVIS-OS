import Foundation

/// Persisted settings for "Fernbetrieb" (Phase 3, Plan "Jarvis proaktiv machen",
/// 2026-09-05): when enabled, this Mac talks to a full Jarvis backend running on
/// another Mac (the Mac Mini "Gehirn", reachable over Tailscale) instead of spawning
/// and managing its own local Python process (see LocalServerController.start()'s
/// early-return and JarvisAPIClient.baseURL below).
///
/// Host + enabled flag are plain UserDefaults (not secret, same keys the Settings UI
/// binds directly via @AppStorage). The token IS the credential and lives only in the
/// macOS Keychain - never in UserDefaults/config.json, same reasoning as
/// push_notify.py's ntfy-topic-in-its-own-file pattern on the backend side.
enum RemoteConnectionSettings {
    private static let keychainService = "com.leon.jarvis.remote"
    private static let keychainAccount = "remote-token"

    /// Kein eigenes Bool-Flag mehr (Phase 1 Meilenstein 1 hatte es hart auf
    /// `false` gesetzt, weil ein STALES `true` in UserDefaults - ohne
    /// zugehoerige gueltige Host/Token-Konfiguration, da die alte
    /// Umschalter-UI schon entfernt war - bei jedem Start einen
    /// unaufgeforderten Keychain-Passwort-Dialog ausloeste, mit keiner
    /// Moeglichkeit mehr, es abzuschalten; live-caught 2026-09-08).
    /// Stattdessen 2026-09-10 wiederhergestellt, aber diesmal strukturell
    /// robust: "aktiv" ist einfach "Host + Token sind beide gesetzt" - ganz
    /// ohne separates Flag kann es keinen stale-true-ohne-Konfiguration-
    /// Zustand mehr geben, der diesen Bug erneut ausloesen koennte. Noetig,
    /// weil JarvisApp beim Testen von einem anderen Mac (Air) aus den alten
    /// Backend auf dem Mac Mini sonst gar nicht mehr erreichen kann, seit
    /// kein lokal gespawnter Prozess mehr existiert.
    static var isEnabled: Bool {
        !host.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && token != nil
    }

    /// Derselbe Mac Mini wie fuer OpenClaw (OpenClawSettings.host) - eine
    /// gemeinsame Adresse statt eines zweiten, separat zu pflegenden Feldes.
    static var host: String {
        OpenClawSettings.host
    }

    static var token: String? {
        get { KeychainStore.read(service: keychainService, account: keychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: keychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: keychainAccount)
            }
        }
    }

    /// `http://<host>:8765` wenn Fernbetrieb aktiv und ein Host gesetzt ist - sonst
    /// `nil`, damit JarvisAPIClient.baseURL sauber auf den lokalen Standard
    /// zurueckfallen kann statt eine kaputte URL zu bauen.
    static var remoteBaseURL: URL? {
        guard isEnabled else { return nil }
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):8765")
    }
}
