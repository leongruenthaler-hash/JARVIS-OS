import Foundation

/// Thin HTTP client for the OpenClaw Gateway (Mac Mini over Tailscale, port 18789) -
/// port of JarvisMobile's APIClient.swift. Replaces JarvisAPIClient.swift's chat path
/// for Phase 1 (Meilenstein 1, "JarvisApp auf OpenClaw umstellen"-Plan, 2026-09-08).
/// Auth is a standard Bearer token (OpenClaw Gateway convention) instead of the old
/// X-Jarvis-Token header; chat goes through OpenClaw's OpenAI-compatible
/// /v1/chat/completions endpoint instead of the old custom /api/chat.
///
/// Non-streaming on purpose: OpenClaw's streaming support for this endpoint hasn't been
/// verified yet (JarvisMobile never needed it either - its chat is also non-streaming).
/// Sentence-by-sentence TTS start still works the same as before because
/// `AppState.streamAndSpeakAnswer` feeds the complete answer through the existing
/// `IncrementalSentenceSplitter` in one pass instead of incrementally per network chunk -
/// a minor behavioral difference (all sentences queued at once vs. as they arrive over
/// the wire), not a capability loss, since synthesis time dominates over the network
/// latency this would have hidden.
struct OpenClawClient {
    func health() async throws -> OpenClawHealth {
        try await get("/health")
    }

    /// history/message are converted into the OpenAI messages array. OpenClaw's agent
    /// keeps session memory server-side (SOUL.md/MEMORY.md) keyed off the `user` field
    /// (OpenClawSettings.sessionUser, a stable per-install id) - without it every call got
    /// a fresh throwaway session, which was the actual cause of Jarvis "forgetting
    /// everything" on app relaunch (see OpenClawSettings.sessionUser for the verified
    /// finding). Returns JarvisApp's existing `ChatResponse` type (JarvisAPIClient.swift)
    /// so `AppState.swift`'s call sites don't need their own response-handling logic
    /// duplicated - `source`/`model` are filled with a fixed "openclaw" label since
    /// OpenClaw doesn't report per-reply provider/model info the way the old backend did.
    func sendChat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        var messages = history.map { entry in
            ChatCompletionMessage(role: entry["role"] ?? "user", content: entry["content"] ?? "")
        }
        messages.append(ChatCompletionMessage(role: "user", content: message))
        let request = ChatCompletionRequest(model: "openclaw", messages: messages, user: OpenClawSettings.sessionUser)
        let response: ChatCompletionResponse = try await post("/v1/chat/completions", body: request)
        let answer = response.choices.first?.message.content ?? ""
        return ChatResponse(answer: answer, source: "openclaw", model: "openclaw")
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: try makeURL(path))
        if let token = OpenClawSettings.token {
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
        if let token = OpenClawSettings.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        request.timeoutInterval = 90
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func makeURL(_ path: String) throws -> URL {
        guard let base = OpenClawSettings.baseURL else { throw OpenClawPairingError.notPaired }
        return URL(string: path, relativeTo: base)!.absoluteURL
    }

    private func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw OpenClawAPIError(statusCode: http.statusCode, body: String(data: data, encoding: .utf8) ?? "")
        }
    }
}

/// OpenClaw's Gateway /health is much simpler than the old Jarvis backend's (just
/// liveness, no provider/model info) - kept as its own type instead of reusing
/// JarvisModels.swift's `ServerHealth`, whose extra fields (provider/activeModel/...)
/// have no OpenClaw equivalent.
struct OpenClawHealth: Decodable {
    let ok: Bool
    let status: String
}

/// OpenAI-compatible chat completions wire format (OpenClaw Gateway
/// /v1/chat/completions, enabled via gateway.http.endpoints.chatCompletions).
private struct ChatCompletionRequest: Encodable {
    let model: String
    let messages: [ChatCompletionMessage]
    let user: String
}

private struct ChatCompletionMessage: Codable {
    let role: String
    let content: String
}

private struct ChatCompletionResponse: Decodable {
    struct Choice: Decodable {
        let message: ChatCompletionMessage
    }
    let choices: [Choice]
}

private struct OpenClawAPIError: LocalizedError {
    let statusCode: Int
    let body: String

    var errorDescription: String? {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return "HTTP \(statusCode)"
        }
        return "HTTP \(statusCode): \(trimmed)"
    }
}

enum OpenClawPairingError: LocalizedError {
    case notPaired

    var errorDescription: String? {
        "Noch nicht mit dem Mac Mini gekoppelt - bitte zuerst in den Einstellungen koppeln."
    }
}
