import Foundation

/// Live "was Jarvis gerade tut"-Feed (2026-09-11, dritte Version) - fragt periodisch
/// scripts/gateway_activity_proxy.mjs (Port 18795) per normalem HTTP ab, statt selbst
/// eine WebSocket-Verbindung zum Gateway zu halten.
///
/// Grund fuer diesen Umweg: ein direkter WS-Connect von diesem Geraet aus (role
/// "operator", scopes ["operator.read"]) verbindet zwar problemlos, aber das
/// anschliessende Session-Subscribe scheitert live reproduzierbar mit "FORBIDDEN:
/// missing scope: operator.read" - dieser Scope wird nur fuer Loopback-Verbindungen
/// automatisch gewaehrt, nicht fuer Remote-/Tailscale-Clients (bestaetigt sowohl direkt
/// vom iPhone als auch per Test-Skript vom Air aus ueber dieselbe Tailscale-Route).
/// Echte Remote-Scopes braeuchten volles kryptographisches Geraete-Pairing (signierte
/// Challenge, v3-Payload-Schema laut OpenClaw-Doku) - ein eigenes, deutlich groesseres
/// Feature. Der Proxy loest das eleganter: er laeuft direkt auf dem Mac Mini, haelt dort
/// die (funktionierende) Loopback-WS-Verbindung, und reicht den Live-Status per HTTP
/// weiter - dasselbe Muster wie jeder andere scripts/*_proxy Dienst hier.
@MainActor
final class GatewayClient: NSObject, ObservableObject {
    struct ActiveTool: Identifiable, Equatable {
        let id: String
        let name: String
        let title: String
    }

    /// Ob der Proxy selbst per HTTP erreichbar ist.
    @Published private(set) var isConnected = false
    /// Ob der Proxy seinerseits erfolgreich mit dem Gateway verbunden ist (aus der
    /// "connected"-Antwort des Proxys) - getrennt von isConnected, falls der Proxy zwar
    /// erreichbar ist, aber seine eigene Gateway-Verbindung gerade neu aufbaut.
    @Published private(set) var isSubscribed = false
    @Published private(set) var currentActivity: String?
    @Published private(set) var activeTools: [ActiveTool] = []
    @Published var connectionError: String?
    /// TEMPORAER (2026-09-11): kurzes, persistentes Protokoll der letzten Ereignisse.
    @Published private(set) var recentEventLog: [String] = []

    private struct ActivityResponse: Decodable {
        let connected: Bool
        let currentActivity: String?
        let activeTools: [ActiveTool]
    }

    private var pollTask: Task<Void, Never>?
    private var sessionUser: String?

    func connect(sessionUser: String) {
        guard pollTask == nil || self.sessionUser != sessionUser else { return }
        disconnect()
        self.sessionUser = sessionUser
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.pollOnce()
                try? await Task.sleep(nanoseconds: 700_000_000)
            }
        }
    }

    func disconnect() {
        pollTask?.cancel()
        pollTask = nil
        isConnected = false
        isSubscribed = false
        currentActivity = nil
        activeTools = []
    }

    private func log(_ line: String) {
        let timestamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        recentEventLog.append("\(timestamp) \(line)")
        if recentEventLog.count > 25 { recentEventLog.removeFirst(recentEventLog.count - 25) }
    }

    private func pollOnce() async {
        guard let sessionUser else { return }
        guard let baseURL = RemoteSettings.gatewayActivityBaseURL, let token = RemoteSettings.gatewayActivityToken else {
            connectionError = "Kein Gateway-Aktivitaets-Proxy-Token konfiguriert."
            return
        }
        var components = URLComponents(url: baseURL.appendingPathComponent("/api/gateway/activity"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "sessionUser", value: sessionUser)]
        guard let url = components?.url else { return }

        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 5

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                isConnected = false
                return
            }
            let decoded = try JSONDecoder().decode(ActivityResponse.self, from: data)
            if !isConnected { log("Proxy erreichbar") }
            isConnected = true
            isSubscribed = decoded.connected
            if decoded.currentActivity != currentActivity { log("activity: \(decoded.currentActivity ?? "-")") }
            if decoded.activeTools.map(\.id) != activeTools.map(\.id) {
                for tool in decoded.activeTools where !activeTools.contains(tool) { log("tool start: \(tool.title)") }
                for tool in activeTools where !decoded.activeTools.contains(tool) { log("tool end: \(tool.title)") }
            }
            currentActivity = decoded.currentActivity
            activeTools = decoded.activeTools
            connectionError = nil
        } catch {
            if isConnected { log("Proxy nicht erreichbar: \(error.localizedDescription)") }
            isConnected = false
        }
    }
}

extension GatewayClient.ActiveTool: Decodable {}
