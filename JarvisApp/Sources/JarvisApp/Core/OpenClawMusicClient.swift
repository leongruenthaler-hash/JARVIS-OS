import Foundation

/// Talks to the Mac Mini's standalone Musik-Proxy (scripts/music_proxy_server.py,
/// port 18797) - replaces the old backend's /api/music/overview endpoint
/// (JarvisAPIClient.swift:202-203), same JSON shape so AppState's existing
/// `MusicOverviewPayload`/`MusicTrack` models need no changes. Only the
/// Dashboard "now playing" overview - playback control stays on OpenClaw chat
/// + the already-installed "managing-apple-music" skill.
enum OpenClawMusicError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Musik-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Musik-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

struct OpenClawMusicClient {
    func overview() async throws -> MusicOverviewPayload {
        guard let baseURL = OpenClawSettings.musicBaseURL, let token = OpenClawSettings.musicToken else {
            throw OpenClawMusicError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/music/overview"))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw OpenClawMusicError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
        return try JSONDecoder().decode(MusicOverviewPayload.self, from: data)
    }
}
