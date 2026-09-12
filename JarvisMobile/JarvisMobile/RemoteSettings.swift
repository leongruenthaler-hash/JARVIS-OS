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

    /// Stable per-install identity sent as the OpenAI-compat `user` field on every
    /// /v1/chat/completions call (2026-09-11, "Jarvis vergisst alles beim Neustart"-Fix).
    /// Verified live: OpenClaw's Gateway keys its server-side session/memory continuity
    /// off this field - two calls with the SAME `user` value share full context (a fact
    /// stated in call 1 with no history array was correctly recalled in call 2), while a
    /// different `user` value sees none of it. Without this, every call previously omitted
    /// `user` entirely, so the Gateway spun up a brand-new throwaway session per request -
    /// the actual root cause of Jarvis appearing to forget everything on app relaunch
    /// (its own long-term memory/MEMORY.md pipeline was fine all along, just never reached
    /// by these apps). Generated once, kept in the Keychain (survives reinstalls the same
    /// way the pairing token does) so it never changes and Jarvis keeps the same
    /// conversation identity across every future launch of this app on this device.
    /// Immer klein geschrieben (2026-09-11-Nachtrag): OpenClaw legt die daraus
    /// abgeleitete Session (agent:main:openai-user:<user>) serverseitig in Kleinbuchstaben
    /// an, aber Swifts UUID().uuidString liefert Grossbuchstaben - ohne diese
    /// Normalisierung abonnierte GatewayClient/der Aktivitaets-Proxy live nachweislich
    /// die FALSCHE (nie existierende) Session und bekam nie Ereignisse. .lowercased() hier
    /// statt an jeder Aufrufstelle einzeln, damit kein zukuenftiger Aufrufer das erneut
    /// vergessen kann.
    static var sessionUser: String {
        if let existing = KeychainStore.read(service: keychainService, account: sessionUserKeychainAccount) {
            return existing.lowercased()
        }
        let generated = "jarvis-mobile-\(UUID().uuidString)".lowercased()
        KeychainStore.save(generated, service: keychainService, account: sessionUserKeychainAccount)
        return generated
    }
    private static let sessionUserKeychainAccount = "session-user-id"

    /// Separate token for the Mac Mini's standalone memory proxy
    /// (scripts/memory_proxy_server.py, port 18794) - same proxy JarvisApp uses.
    /// Serves OpenClaw's own USER.md/MEMORY.md/installed-skills list as structured
    /// facts, replacing the previous "ask Jarvis via chat to dump MEMORY.md as
    /// plain text" hack in MemoryView.swift (fragile, and only ever showed
    /// MEMORY.md - never USER.md or Jarvis's own tool/skill inventory, which is
    /// exactly what was missing here, 2026-09-11).
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
    /// proxy.mjs, Port 18795, 2026-09-11) - siehe JarvisApp's gleichnamiges Pendant
    /// (OpenClawSettings.gatewayActivityToken) fuer die volle Begruendung: eine direkte
    /// WebSocket-Verbindung von diesem Geraet aus scheiterte live mit "FORBIDDEN:
    /// missing scope: operator.read" (Remote-Verbindungen bekommen diesen Scope ohne
    /// echtes kryptographisches Geraete-Pairing nicht gewaehrt) - dieser Proxy haelt
    /// stattdessen die (funktionierende) Loopback-Verbindung und reicht per HTTP weiter.
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

    /// Token fuer den Mac Mini's Gesundheits-Proxy (scripts/health_proxy_server.py,
    /// Port 18801, 2026-09-12) - anders als alle anderen Proxys hier PUSHT dieses
    /// Geraet Daten dorthin (HealthKit gibt es nur auf iOS, der Mac Mini kann Apple
    /// Health/Watch-Werte nicht selbst abfragen), statt nur zu lesen.
    static var healthToken: String? {
        get { KeychainStore.read(service: keychainService, account: healthKeychainAccount) }
        set {
            if let newValue, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                KeychainStore.save(newValue, service: keychainService, account: healthKeychainAccount)
            } else {
                KeychainStore.delete(service: keychainService, account: healthKeychainAccount)
            }
        }
    }
    private static let healthKeychainAccount = "health-proxy-token"

    /// Same Mac Mini host as `baseURL`, different port - see
    /// scripts/health_proxy_server.py::PORT.
    static var healthBaseURL: URL? {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else { return nil }
        return URL(string: "http://\(trimmedHost):18801")
    }
}
