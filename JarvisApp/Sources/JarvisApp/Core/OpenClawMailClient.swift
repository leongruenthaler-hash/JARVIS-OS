import Foundation

/// Talks to the Mac Mini's standalone Mail-Proxy (scripts/mail_proxy_server.py,
/// port 18796) - replaces the old backend's /api/mail/overview|scan-folders
/// endpoints (JarvisAPIClient.swift:155-199), same JSON shapes so AppState's
/// existing `MailOverviewPayload`/`ScanProgress` models need no changes.
/// Deliberately its own client/token, not routed through OpenClaw's chat agent -
/// overview/scan-status here are fast, deterministic status reads, not something
/// that benefits from an LLM round-trip (unlike free-text mail commands, which
/// stay on `performMailCommand` -> OpenClaw chat + the already-installed
/// apple-mail-macos skill).
///
/// Also exposes `/api/mail/summaries`/`/api/mail/unsummarized` - the new,
/// per-mail summary feed (2026-09-12) that replaces the old backend's bundled
/// MailBackgroundWorker output. This client only *reads* summaries; they are
/// written by the "mail-summary-watch" OpenClaw automation, not by JarvisApp
/// itself.
enum OpenClawMailError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Mail-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Mail-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

struct MailSummary: Decodable, Identifiable, Equatable {
    let messageId: String
    let sender: String
    let subject: String
    let received: String
    let summary: String
    let createdAt: String

    var id: String { messageId }

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case sender, subject, received, summary
        case createdAt = "created_at"
    }
}

private struct EmptyMailRequestBody: Encodable {}

struct OpenClawMailClient {
    func overview() async throws -> MailOverviewPayload {
        try await get("/api/mail/overview")
    }

    func scanStatus() async throws -> ScanProgress {
        try await get("/api/mail/scan-status")
    }

    func startFolderScan() async throws -> ScanProgress {
        try await post("/api/mail/scan-folders", body: EmptyMailRequestBody())
    }

    func summaries(limit: Int = 50) async throws -> [MailSummary] {
        struct Response: Decodable { let entries: [MailSummary] }
        let response: Response = try await get("/api/mail/summaries?limit=\(limit)")
        return response.entries
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let baseURL = OpenClawSettings.mailBaseURL, let token = OpenClawSettings.mailToken else {
            throw OpenClawMailError.notPaired
        }
        var request = URLRequest(url: URL(string: path, relativeTo: baseURL) ?? baseURL.appendingPathComponent(path))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        guard let baseURL = OpenClawSettings.mailBaseURL, let token = OpenClawSettings.mailToken else {
            throw OpenClawMailError.notPaired
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
            throw OpenClawMailError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
    }
}
