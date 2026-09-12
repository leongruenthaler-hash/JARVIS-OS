import Foundation

/// Talks to the Mac Mini's standalone Kalender-Proxy
/// (scripts/calendar_proxy_server.py, port 18798) - replaces the old backend's
/// /api/calendar/overview endpoint, same JSON shape so AppState's existing
/// `CalendarOverviewPayload` model needs no changes. Only the Dashboard
/// overview - Termine/Erinnerungen anlegen/loeschen laeuft weiterhin ueber
/// OpenClaw-Chat.
enum OpenClawCalendarError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Kalender-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Kalender-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

struct OpenClawCalendarClient {
    func overview() async throws -> CalendarOverviewPayload {
        guard let baseURL = OpenClawSettings.calendarBaseURL, let token = OpenClawSettings.calendarToken else {
            throw OpenClawCalendarError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/calendar/overview"))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw OpenClawCalendarError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
        return try JSONDecoder().decode(CalendarOverviewPayload.self, from: data)
    }
}
