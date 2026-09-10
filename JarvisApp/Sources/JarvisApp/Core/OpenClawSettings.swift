import Foundation

/// Pairing settings for JarvisApp's OpenClaw connection (Phase 1, "JarvisApp auf
/// OpenClaw umstellen"-Plan, 2026-09-08) - port of JarvisMobile's RemoteSettings.swift.
/// Unlike the old RemoteConnectionSettings (which toggled between a locally-spawned
/// Python process and a remote one, both the SAME `local_server.py`), JarvisApp now has
/// NO local mode at all: it always talks to OpenClaw's Gateway on the Mac Mini, exactly
/// like JarvisMobile. Host is plain UserDefaults; the pairing token is the real
/// credential and lives only in the Keychain (reuses the existing KeychainStore.swift).
enum OpenClawSettings {
    static let hostKey = "JarvisOpenClawHost"
    private static let keychainService = "com.leon.jarvis.mac.openclaw"
    private static let keychainAccount = "gateway-token"

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

    /// `nil` when no host is configured yet, so callers can show a pairing prompt
    /// instead of firing requests at a bogus URL. Port 18789 is OpenClaw's Gateway
    /// (WS+HTTP multiplex) - same port JarvisMobile already uses.
    static var baseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18789")
    }

    /// Separate token for the Mac Mini's small standalone TTS proxy
    /// (scripts/tts_proxy_server.py, port 18790) - same proxy JarvisMobile uses,
    /// port of RemoteSettings.ttsToken (2026-09-10: replaces the old backend's
    /// EdgeTTSService/tts_bridge.py dependency, same reasoning as JarvisMobile -
    /// Killian via this proxy sounded noticeably better than any on-device option
    /// tried). Deliberately a different secret than the gateway token, since this
    /// is a separate process with its own auth.
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
    private static let ttsKeychainAccount = "tts-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/tts_proxy_server.py::PORT.
    static var ttsBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18790")
    }
}
