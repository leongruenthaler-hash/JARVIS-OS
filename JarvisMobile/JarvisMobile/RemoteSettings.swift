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
    /// prompt instead of firing requests at a bogus URL.
    static var baseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):8765")
    }
}
