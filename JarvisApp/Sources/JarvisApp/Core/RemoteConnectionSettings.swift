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
    static let enabledKey = "JarvisRemoteModeEnabled"
    static let hostKey = "JarvisRemoteHost"
    private static let keychainService = "com.leon.jarvis.remote"
    private static let keychainAccount = "remote-token"

    static var isEnabled: Bool {
        UserDefaults.standard.bool(forKey: enabledKey)
    }

    /// Tailscale-IP oder MagicDNS-Name des Mac Mini, z.B. "100.115.128.74" - ohne
    /// Schema und ohne Port.
    static var host: String {
        UserDefaults.standard.string(forKey: hostKey) ?? ""
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
