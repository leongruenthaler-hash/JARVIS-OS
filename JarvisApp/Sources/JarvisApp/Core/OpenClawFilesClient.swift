import Foundation

/// Talks to the Mac Mini's standalone file-search proxy (scripts/files_proxy_server.py,
/// port 18792) - replaces the old backend's /api/files/* endpoints
/// (JarvisAPIClient.swift:214-246), same JSON shapes so FilesView/AppState's existing
/// `ScanProgress`/`FileSearchPayload`/`FileSearchResult` models need no changes.
/// Deliberately its own client/token, not routed through OpenClaw's chat agent - file
/// search here is a fast, deterministic index lookup, not something that benefits from
/// an LLM round-trip.
enum OpenClawFilesError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Datei-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Datei-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

private struct EmptyFilesRequestBody: Encodable {}

struct OpenClawFilesClient {
    func status() async throws -> ScanProgress {
        try await get("/api/files/status")
    }

    func startScan() async throws -> ScanProgress {
        try await post("/api/files/scan", body: EmptyFilesRequestBody())
    }

    func search(query: String) async throws -> FileSearchPayload {
        struct Request: Encodable { let query: String }
        return try await post("/api/files/search", body: Request(query: query))
    }

    func moveSearchResults(query: String, targetFolder: String) async throws -> String {
        struct Request: Encodable {
            let query: String
            let targetFolder: String
            enum CodingKeys: String, CodingKey {
                case query
                case targetFolder = "target_folder"
            }
        }
        struct Response: Decodable { let message: String; let progress: ScanProgress? }
        let response: Response = try await post("/api/files/move-search-results", body: Request(query: query, targetFolder: targetFolder))
        return response.message
    }

    func resetIndex() async throws -> ScanProgress {
        try await post("/api/files/reset", body: EmptyFilesRequestBody())
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let baseURL = OpenClawSettings.filesBaseURL, let token = OpenClawSettings.filesToken else {
            throw OpenClawFilesError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        guard let baseURL = OpenClawSettings.filesBaseURL, let token = OpenClawSettings.filesToken else {
            throw OpenClawFilesError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
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
            throw OpenClawFilesError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
    }
}
