import Foundation

/// Talks to the Mac Mini's standalone Fotos-Proxy (scripts/photos_proxy_server.py,
/// port 18793) - replaces the old backend's /api/photos/permission-status|
/// permission|scan|reset|vision-status|vision/analyze|vision/reset endpoints
/// (JarvisAPIClient.swift:178-262), same JSON shapes so AppState's existing
/// `ScanProgress`/`LocalVisionStatus` models need no changes. Deliberately its own
/// client/token, not routed through OpenClaw's chat agent - permission/scan/vision
/// status here are fast, deterministic status reads, not something that benefits
/// from an LLM round-trip (unlike free-text photo search, which stays on
/// `performPhotoCommand` -> OpenClaw chat + the already-installed jarvis-photos skill).
enum OpenClawPhotosError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Fotos-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Fotos-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

private struct EmptyPhotosRequestBody: Encodable {}

struct OpenClawPhotosClient {
    func status() async throws -> ScanProgress {
        try await get("/api/photos/status")
    }

    func visionProgress() async throws -> ScanProgress {
        try await get("/api/photos/vision-progress")
    }

    func permissionStatus() async throws -> String {
        struct Response: Decodable { let status: String }
        let response: Response = try await get("/api/photos/permission-status")
        return response.status
    }

    func requestPermission() async throws -> String {
        struct Response: Decodable { let message: String; let progress: ScanProgress? }
        let response: Response = try await post("/api/photos/permission", body: EmptyPhotosRequestBody())
        return response.message
    }

    func startScan() async throws -> ScanProgress {
        try await post("/api/photos/scan", body: EmptyPhotosRequestBody())
    }

    func resetIndex() async throws -> ScanProgress {
        try await post("/api/photos/reset", body: EmptyPhotosRequestBody())
    }

    func localVisionStatus() async throws -> LocalVisionStatus {
        try await get("/api/photos/vision-status")
    }

    func startLocalVisionAnalysis() async throws -> ScanProgress {
        try await post("/api/photos/vision/analyze", body: EmptyPhotosRequestBody())
    }

    func resetLocalVisionDescriptions() async throws -> ScanProgress {
        try await post("/api/photos/vision/reset", body: EmptyPhotosRequestBody())
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let baseURL = OpenClawSettings.photosBaseURL, let token = OpenClawSettings.photosToken else {
            throw OpenClawPhotosError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        guard let baseURL = OpenClawSettings.photosBaseURL, let token = OpenClawSettings.photosToken else {
            throw OpenClawPhotosError.notPaired
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
            throw OpenClawPhotosError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
    }
}
