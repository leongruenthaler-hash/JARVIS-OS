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

    /// history/message are converted into the OpenAI messages array; OpenClaw's
    /// agent itself keeps session memory server-side (SOUL.md/MEMORY.md), so
    /// the history array here is mainly for a fresh/stateless call context.
    func sendChat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        var messages = history.map { entry in
            ChatCompletionMessage(role: entry["role"] ?? "user", content: entry["content"] ?? "")
        }
        messages.append(ChatCompletionMessage(role: "user", content: message))
        let request = ChatCompletionRequest(model: "openclaw", messages: messages)
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
        request.timeoutInterval = 90
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
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
