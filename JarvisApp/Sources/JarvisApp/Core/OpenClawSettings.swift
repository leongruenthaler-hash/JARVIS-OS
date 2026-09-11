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

    /// Separate token for the Mac Mini's standalone file-search proxy
    /// (scripts/files_proxy_server.py, port 18792) - replaces the old backend's
    /// /api/files/* endpoints (2026-09-10, "Dateien" Fachbereich Migration).
    static var filesToken: String? {
        get { KeychainStore.read(service: keychainService, account: filesKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: filesKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: filesKeychainAccount)
            }
        }
    }
    private static let filesKeychainAccount = "files-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/files_proxy_server.py::PORT.
    static var filesBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18792")
    }

    /// Separate token for the Mac Mini's standalone Fotos-Proxy
    /// (scripts/photos_proxy_server.py, port 18793) - replaces the old backend's
    /// /api/photos/permission-status|permission|scan|reset|vision-status|
    /// vision/analyze|vision/reset endpoints (2026-09-11, "Fotos" Fachbereich
    /// Migration). Freitextsuche/Album/Export laufen weiterhin ueber OpenClaw-Chat
    /// (performPhotoCommand + der bereits installierte jarvis-photos-Skill).
    static var photosToken: String? {
        get { KeychainStore.read(service: keychainService, account: photosKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: photosKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: photosKeychainAccount)
            }
        }
    }
    private static let photosKeychainAccount = "photos-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/photos_proxy_server.py::PORT.
    static var photosBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18793")
    }

    /// Stable per-install identity sent as the OpenAI-compat `user` field on every
    /// /v1/chat/completions call (2026-09-11, "Jarvis vergisst alles beim Neustart"-Fix,
    /// same fix as JarvisMobile's RemoteSettings.sessionUser - see there for the full,
    /// live-verified finding: OpenClaw's Gateway keys server-side session/memory
    /// continuity off this field, and every call previously omitted it entirely, so each
    /// request got a brand-new throwaway session). Generated once, kept in the Keychain so
    /// it never changes across future launches on this Mac.
    /// Immer klein geschrieben (2026-09-11-Nachtrag) - siehe JarvisMobile's
    /// RemoteSettings.sessionUser fuer die volle, live bestaetigte Begruendung: OpenClaw
    /// legt die Session serverseitig klein geschrieben an, UUID().uuidString liefert aber
    /// Grossbuchstaben - ohne diese Normalisierung abonnierten GatewayClient/der
    /// Aktivitaets-Proxy nachweislich die falsche, nie existierende Session.
    static var sessionUser: String {
        if let existing = KeychainStore.read(service: keychainService, account: sessionUserKeychainAccount) {
            return existing.lowercased()
        }
        let generated = "jarvis-mac-\(UUID().uuidString)".lowercased()
        KeychainStore.save(generated, service: keychainService, account: sessionUserKeychainAccount)
        return generated
    }
    private static let sessionUserKeychainAccount = "session-user-id"

    /// Separate token for the Mac Mini's standalone memory proxy
    /// (scripts/memory_proxy_server.py, port 18794) - replaces the old backend's
    /// /api/memory/facts* endpoints (2026-09-11, "Gedaechtnis"-Fachbereich Migration).
    /// Serves OpenClaw's own USER.md/MEMORY.md instead of the now-irrelevant
    /// app/memory.py long_memory.json.
    static var memoryToken: String? {
        get { KeychainStore.read(service: keychainService, account: memoryKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: memoryKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: memoryKeychainAccount)
            }
        }
    }
    private static let memoryKeychainAccount = "memory-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/memory_proxy_server.py::PORT.
    static var memoryBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18794")
    }

    /// Token fuer den Mac Mini's Gateway-Aktivitaets-Proxy (scripts/gateway_activity_
    /// proxy.mjs, Port 18795, 2026-09-11) - loest das "role operator + scopes
    /// [operator.read] wird fuer Remote-WebSocket-Verbindungen verweigert"-Problem
    /// (live verifiziert: funktioniert nur ueber Loopback, echte Remote-Scopes
    /// braeuchten volles kryptographisches Geraete-Pairing). Dieser Proxy haelt die
    /// (funktionierende) Loopback-Verbindung zum Gateway und reicht den Live-Status
    /// per normalem HTTP-Polling weiter, wie jeder andere Proxy hier auch.
    static var gatewayActivityToken: String? {
        get { KeychainStore.read(service: keychainService, account: gatewayActivityKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: gatewayActivityKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: gatewayActivityKeychainAccount)
            }
        }
    }
    private static let gatewayActivityKeychainAccount = "gateway-activity-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/gateway_activity_proxy.mjs::PORT.
    static var gatewayActivityBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18795")
    }
}
