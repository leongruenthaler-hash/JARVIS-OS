import Foundation

/// Talks to the Mac Mini's standalone memory proxy (scripts/memory_proxy_server.py,
/// port 18794) - replaces the old backend's /api/memory/facts* endpoints
/// (JarvisAPIClient.swift), which read app/memory.py's long_memory.json - a store
/// OpenClaw's migration has made irrelevant, since OpenClaw itself is now the actual
/// "brain" and keeps its own durable memory in ~/.openclaw/workspace/USER.md (curated
/// user directives) and MEMORY.md (curated long-term facts, populated by a nightly
/// "dreaming" promotion job and possibly empty on a fresh setup - not a bug).
///
/// Confirm/reject have no real equivalent here (see the proxy's own module docstring):
/// everything this proxy returns is already durably curated by OpenClaw itself, so it
/// always comes back with status "confirmed" - MemoryView.swift's existing
/// `if fact.status != "confirmed"` checks make those buttons disappear on their own,
/// no UI change needed. Delete is real: it removes the matching line (and, for USER.md,
/// its `<!-- observed -->` comment) from the actual source file.
enum OpenClawMemoryError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Speicher-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Speicher-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

struct OpenClawMemoryClient {
    func facts(search: String = "", category: String = "") async throws -> MemoryFactsResponse {
        var queryItems: [URLQueryItem] = []
        if !search.isEmpty { queryItems.append(URLQueryItem(name: "search", value: search)) }
        if !category.isEmpty { queryItems.append(URLQueryItem(name: "category", value: category)) }
        var path = "/api/memory/facts"
        if !queryItems.isEmpty {
            var components = URLComponents()
            components.queryItems = queryItems
            path += components.percentEncodedQuery.map { "?\($0)" } ?? ""
        }
        return try await get(path)
    }

    func recentActivity() async throws -> [ActivityEvent] {
        struct Response: Decodable { let events: [ActivityEvent] }
        let response: Response = try await get("/api/memory/activity")
        return response.events
    }

    func deleteFact(id: String) async throws {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let _: Response = try await post("/api/memory/facts/delete", body: Request(id: id))
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let baseURL = OpenClawSettings.memoryBaseURL, let token = OpenClawSettings.memoryToken else {
            throw OpenClawMemoryError.notPaired
        }
        var request = URLRequest(url: URL(string: path, relativeTo: baseURL)!.absoluteURL)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        guard let baseURL = OpenClawSettings.memoryBaseURL, let token = OpenClawSettings.memoryToken else {
            throw OpenClawMemoryError.notPaired
        }
        var request = URLRequest(url: URL(string: path, relativeTo: baseURL)!.absoluteURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 30
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw OpenClawMemoryError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
    }
}
