import Foundation

/// Pairing settings for this iPhone app (Phase 5, Plan "Jarvis proaktiv
/// machen", 2026-09-05): unlike the Mac app, JarvisMobile has no local mode
/// at all - it ALWAYS talks to a remote Jarvis backend (the Mac Mini, over
/// Tailscale). Host is plain UserDefaults; the pairing token is the real
/// credential and lives only in the Keychain (same reasoning as
/// JarvisApp's RemoteConnectionSettings/push_notify.py's ntfy-topic file).
enum RemoteSettings {
    static let hostKey = "JarvisMobileHost"
    private static let keychainService = "com.leon.jarvis.mobile"
    private static let keychainAccount = "remote-token"
    private static let ttsKeychainAccount = "tts-proxy-token"

    /// Tailscale-IP oder MagicDNS-Name des Mac Mini, ohne Schema und Port.
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

    static var isPaired: Bool {
        !host.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && token != nil
    }

    /// `nil` when no host is configured yet, so callers can show a pairing
    /// prompt instead of firing requests at a bogus URL. Port 18789 is
    /// OpenClaw's Gateway (WS+HTTP multiplex) - replaces the old Jarvis
    /// local_server.py on 8765 as of the OpenClaw migration (2026-09-06).
    static var baseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18789")
    }

    /// Separate token for the Mac Mini's small standalone TTS proxy (Edge-TTS
    /// via scripts/tts_proxy_server.py, port 18790) - deliberately NOT the
    /// same secret as OpenClaw's own gateway token: this is a different
    /// process with its own auth, not something we can read out of OpenClaw's
    /// internal config. Same Keychain-only storage reasoning as `token`.
    static var ttsToken: String? {
        get { KeychainStore.read(service: keychainService, account: ttsKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: ttsKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: ttsKeychainAccount)
            }
        }
    }

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/tts_proxy_server.py::PORT.
    static var ttsBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18790")
    }
}
