import Foundation

/// Thin HTTP client for the Jarvis backend (Mac Mini over Tailscale) - same
/// X-Jarvis-Token header pattern as JarvisApp's JarvisAPIClient.swift on
/// macOS, but always remote (no local baseURL fallback: this app has no
/// local core to spawn at all).
struct APIClient {
    func health() async throws -> ServerHealth {
        try await get("/api/health")
    }

    func sendChat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        struct Request: Encodable { let message: String; let history: [[String: String]] }
        return try await post("/api/chat", body: Request(message: message, history: history))
    }

    func proactivityEvents() async throws -> [ProactiveEvent] {
        let response: ProactiveEventsResponse = try await get("/api/proactivity/events")
        return response.events
    }

    @discardableResult
    func snoozeProactivityEvent(dedupKey: String, minutes: Int = 60) async throws -> Bool {
        struct Request: Encodable {
            let dedupKey: String
            let minutes: Int
            enum CodingKeys: String, CodingKey { case dedupKey = "dedup_key"; case minutes }
        }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/proactivity/snooze", body: Request(dedupKey: dedupKey, minutes: minutes))
        return response.ok
    }

    @discardableResult
    func dismissProactivityEvent(dedupKey: String) async throws -> Bool {
        struct Request: Encodable {
            let dedupKey: String
            enum CodingKeys: String, CodingKey { case dedupKey = "dedup_key" }
        }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/proactivity/dismiss", body: Request(dedupKey: dedupKey))
        return response.ok
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: try makeURL(path))
        if let token = RemoteSettings.token {
            request.setValue(token, forHTTPHeaderField: "X-Jarvis-Token")
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
            request.setValue(token, forHTTPHeaderField: "X-Jarvis-Token")
        }
        request.timeoutInterval = 60
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
