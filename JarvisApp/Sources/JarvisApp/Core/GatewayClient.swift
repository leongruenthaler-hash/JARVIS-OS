import Foundation

/// Live "was Jarvis gerade tut"-Feed (2026-09-11, dritte Version) - direkter Port von
/// JarvisMobile/GatewayClient.swift: fragt periodisch scripts/gateway_activity_proxy.mjs
/// (Port 18795) per normalem HTTP ab, statt selbst eine WebSocket-Verbindung zum Gateway
/// zu halten. Siehe dort fuer die volle Begruendung - kurz: ein direkter WS-Connect mit
/// role "operator" scheitert beim Session-Subscribe live mit "FORBIDDEN: missing scope:
/// operator.read" fuer jede Nicht-Loopback-Verbindung (bestaetigt per Testskript ueber
/// dieselbe Tailscale-Route); dieser Proxy haelt stattdessen die funktionierende
/// Loopback-Verbindung direkt auf dem Mac Mini und reicht den Status per HTTP weiter.
@MainActor
final class GatewayClient: NSObject, ObservableObject {
    struct ActiveTool: Identifiable, Equatable, Decodable {
        let id: String
        let name: String
        let title: String
    }

    @Published private(set) var isConnected = false
    @Published private(set) var isSubscribed = false
    @Published private(set) var currentActivity: String?
    @Published private(set) var activeTools: [ActiveTool] = []
    @Published var connectionError: String?

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

    private func pollOnce() async {
        guard let sessionUser else { return }
        guard let baseURL = OpenClawSettings.gatewayActivityBaseURL, let token = OpenClawSettings.gatewayActivityToken else {
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
            isConnected = true
            isSubscribed = decoded.connected
            currentActivity = decoded.currentActivity
            activeTools = decoded.activeTools
            connectionError = nil
        } catch {
            isConnected = false
        }
    }
}
