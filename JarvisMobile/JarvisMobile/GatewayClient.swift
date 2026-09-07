import Foundation

/// Direct WebSocket client for OpenClaw's Gateway protocol (docs.openclaw.ai/
/// gateway/protocol) - used instead of the simpler REST /v1/chat/completions
/// specifically to get LIVE tool-execution events while a message is being
/// answered (2026-09-07: user wants to see, in real time, which skill/memory
/// Jarvis is actually using - REST has no equivalent, only WS's per-session
/// event subscription does).
///
/// The exact field names for tool-lifecycle events are only partially
/// documented upstream, so every parsed event ALSO republishes its raw JSON
/// via `rawEvents` - if `toolEvents`/`messageEvents` come out empty or wrong
/// while `rawEvents` clearly shows tool activity, that's the signal the
/// field-name guesses below need adjusting, not that nothing is happening.
@MainActor
final class GatewayClient: NSObject, ObservableObject {
    struct ToolEvent: Identifiable, Equatable {
        let id = UUID()
        let toolName: String
        let state: String
        let detail: String?
        let date = Date()
    }

    @Published private(set) var isConnected = false
    @Published private(set) var toolEvents: [ToolEvent] = []
    @Published private(set) var lastAssistantText: String?
    @Published var connectionError: String?
    /// Last few raw server frames, newest last - diagnostic escape hatch
    /// described above.
    @Published private(set) var rawEvents: [String] = []

    private var task: URLSessionWebSocketTask?
    private var requestCounter = 0
    private let sessionKey = "agent:main:main"

    func connect() {
        guard let host = GatewayClient.wsHost() else {
            connectionError = "Keine Mac-Mini-Adresse konfiguriert."
            return
        }
        guard let token = RemoteSettings.token else {
            connectionError = "Kein Token konfiguriert."
            return
        }
        guard let url = URL(string: "ws://\(host):18789") else { return }

        let request = URLRequest(url: url)
        let session = URLSession(configuration: .default, delegate: nil, delegateQueue: nil)
        let task = session.webSocketTask(with: request)
        self.task = task
        task.resume()
        receiveLoop()
        sendConnectRequest(token: token)
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
    }

    /// Sends a chat message over the SAME connection whose tool events we
    /// subscribe to, so activity can actually be attributed to this request
    /// (a message sent via the separate REST endpoint has no guaranteed
    /// relationship to this session's event stream).
    func send(message: String) {
        toolEvents.removeAll()
        lastAssistantText = nil
        // "channel":"webchat" aenderte NICHTS am SESSION_MUTATION_TARGET_
        // REQUIRED-Fehler - das war der falsche Ansatz. Der health-Event
        // zeigte an anderer Stelle "target":"owner" (im Heartbeat-Config) -
        // Versuch: ein eigenes "target"-Feld statt/neben "channel".
        sendRequest(method: "chat.send", params: [
            "key": sessionKey,
            "message": message,
            "queueMode": "followup",
            "target": "owner",
        ])
    }

    private static func wsHost() -> String? {
        let trimmed = RemoteSettings.host.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func nextID() -> String {
        requestCounter += 1
        return "req-\(requestCounter)"
    }

    private func sendConnectRequest(token: String) {
        sendRequest(method: "connect", params: [
            "minProtocol": 4,
            "maxProtocol": 4,
            // "gateway-client"/"backend" ist ein in der OpenClaw-Doku
            // bestaetigtes gueltiges Paar fuer vertrauenswuerdige Clients mit
            // geteiltem Gateway-Token (statt eigener Geraete-Identitaet) -
            // unser urspruenglich geratenes "jarvis-mobile"/"operator" wurde
            // vom Server mit INVALID_REQUEST abgelehnt (siehe rawEvents).
            "client": [
                "id": "gateway-client",
                "version": "1.0.0",
                "platform": "ios",
                "mode": "backend",
            ],
            // role "operator" liess sich verbinden + abonnieren, aber
            // chat.send (Schreiben) scheiterte mit SESSION_MUTATION_TARGET_
            // REQUIRED - laut Doku brauchen SCHREIBENDE Aktionen von einem
            // Remote-Client (wir sind ueber Tailscale, nicht Loopback) eine
            // echte, genehmigte Geraete-Identitaet. role "node" + "device"
            // loest eine Pairing-Anfrage aus, die per autoApproveCidrs fuer
            // unseren Tailscale-Bereich (100.64.0.0/10) automatisch
            // genehmigt werden sollte (bereits auf dem Mac Mini konfiguriert).
            "role": "node",
            "device": [
                "id": "jarvis-mobile-leon-iphone",
                "name": "iPhone von Leon (JarvisMobile)",
                "platform": "ios",
            ],
            "scopes": ["operator.read", "operator.write"],
            "caps": [],
            "auth": ["token": token],
            "locale": "de-DE",
            "userAgent": "JarvisMobile/1.0",
        ])
    }

    private func subscribeToSession() {
        // Feld heisst "key" nicht "sessionKey" (Server-Fehler #1).
        // includeApprovals lehnte sowohl true (fehlendes Scope
        // operator.approvals) als auch false ("must be equal to constant")
        // ab - ein Optional-mit-Konstante-Feld, das offenbar nur gueltig
        // ist, wenn es GANZ WEGGELASSEN wird, statt explizit false zu
        // setzen.
        sendRequest(method: "sessions.messages.subscribe", params: [
            "key": sessionKey,
        ])
    }

    private func sendRequest(method: String, params: [String: Any]) {
        let payload: [String: Any] = ["type": "req", "id": nextID(), "method": method, "params": params]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        task?.send(.string(text)) { [weak self] error in
            if let error {
                Task { @MainActor in self?.connectionError = "Senden fehlgeschlagen: \(error.localizedDescription)" }
            }
        }
    }

    private func receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                switch result {
                case .failure(let error):
                    self.connectionError = "Verbindung verloren: \(error.localizedDescription)"
                    self.isConnected = false
                case .success(let message):
                    if case .string(let text) = message {
                        self.handleIncoming(text)
                    }
                    self.receiveLoop()
                }
            }
        }
    }

    private func handleIncoming(_ text: String) {
        appendRaw(text)
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let type = json["type"] as? String

        if type == "res" {
            // A "connect" response success implies the handshake worked -
            // move straight to subscribing so tool events start flowing.
            if !isConnected, (json["ok"] as? Bool) == true {
                isConnected = true
                subscribeToSession()
            }
            return
        }

        guard type == "event", let event = json["event"] as? String,
              let payload = json["payload"] as? [String: Any] else { return }

        switch event {
        case "connect.challenge":
            // Token-based auth (already proven to work over REST with the
            // same token) doesn't need the signed-nonce device-identity
            // path - the plain "connect" request above is sent either way.
            break
        case "session.tool", "agent.tool", "tool", "session.tool_call":
            let toolName = (payload["toolName"] as? String) ?? (payload["tool"] as? String) ?? (payload["name"] as? String) ?? "unbekannt"
            let state = (payload["state"] as? String) ?? (payload["status"] as? String) ?? "unbekannt"
            let detail = (payload["output"] as? String) ?? (payload["summary"] as? String)
            toolEvents.append(ToolEvent(toolName: toolName, state: state, detail: detail))
        case "session.message", "agent.message", "chat":
            if let text = (payload["text"] as? String) ?? (payload["content"] as? String) {
                lastAssistantText = text
            }
        default:
            break
        }
    }

    private func appendRaw(_ text: String) {
        rawEvents.append(text)
        if rawEvents.count > 40 { rawEvents.removeFirst(rawEvents.count - 40) }
    }
}
