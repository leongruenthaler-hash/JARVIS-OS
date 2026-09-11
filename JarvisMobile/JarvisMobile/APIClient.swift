import Foundation

/// Thin HTTP client for the OpenClaw Gateway (Mac Mini over Tailscale/
/// tailscale-serve on port 18789). Replaces the old Jarvis local_server.py
/// client (2026-09-06 OpenClaw migration) - auth is now a standard Bearer
/// token (OpenClaw Gateway convention) instead of the old X-Jarvis-Token
/// header, and chat goes through OpenClaw's OpenAI-compatible
/// /v1/chat/completions endpoint instead of a custom /api/chat.
struct APIClient {
    func health() async throws -> ServerHealth {
        try await get("/health")
    }

    /// history/message are converted into the OpenAI messages array. OpenClaw's agent
    /// keeps session memory server-side (SOUL.md/MEMORY.md) keyed off the `user` field
    /// (RemoteSettings.sessionUser, a stable per-install id) - without it every call got a
    /// fresh throwaway session, which was the actual cause of Jarvis "forgetting
    /// everything" on app relaunch (see RemoteSettings.sessionUser for the verified
    /// finding). The history array is still sent for the current chat screen's own
    /// context, on top of whatever the Gateway retains server-side.
    func sendChat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        var messages = history.map { entry in
            ChatCompletionMessage(role: entry["role"] ?? "user", content: entry["content"] ?? "")
        }
        messages.append(ChatCompletionMessage(role: "user", content: message))
        let request = ChatCompletionRequest(model: "openclaw", messages: messages, user: RemoteSettings.sessionUser)
        let response: ChatCompletionResponse = try await post("/v1/chat/completions", body: request)
        let answer = response.choices.first?.message.content ?? ""
        return ChatResponse(answer: answer)
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: try makeURL(path))
        if let token = RemoteSettings.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        var request = URLRequest(url: try makeURL(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = RemoteSettings.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        // 300s statt 90s - ein agentischer OpenClaw-Auftrag mit mehreren
        // Werkzeug-Aufrufen (z.B. Mails durchsuchen + Kalendereintraege
        // anlegen) kann deutlich laenger dauern als eine einfache
        // Chat-Antwort (live beobachtet 2026-09-09).
        request.timeoutInterval = 300
        request.httpBody = try JSONEncoder().encode(body)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            try validate(response, data: data)
            return try JSONDecoder().decode(T.self, from: data)
        } catch let error as URLError where error.code == .networkConnectionLost || error.code == .timedOut {
            // Ein einmaliger stiller Retry - eine waehrend eines langen
            // Auftrags abgerissene Verbindung (Tailscale-Hakler, kurzes
            // Backgrounden) ist oft voruebergehend (live beobachtet
            // 2026-09-09: "The network connection was lost" nach einer
            // Mail+Kalender-Anfrage). Bleibt das Handy die GANZE Zeit
            // gesperrt/im Hintergrund, killt iOS auch diesen Versuch - das
            // ist eine Plattformgrenze, kein Bug, den ein Retry uebertuenchen
            // koennte.
            let (data, response) = try await URLSession.shared.data(for: request)
            try validate(response, data: data)
            return try JSONDecoder().decode(T.self, from: data)
        }
    }

    private func makeURL(_ path: String) throws -> URL {
        guard let base = RemoteSettings.baseURL else { throw PairingError.notPaired }
        return URL(string: path, relativeTo: base)!.absoluteURL
    }

    private func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError(statusCode: http.statusCode, body: String(data: data, encoding: .utf8) ?? "")
        }
    }
}
