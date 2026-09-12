import Foundation

/// Talks to the Mac Mini's standalone Automationen-Proxy
/// (scripts/automations_proxy_server.py, port 18800) - listet die echten
/// OpenClaw-Cronjobs (rein lesend, Steuerung bleibt Sache von
/// `openclaw cron edit/run` im Terminal).
enum OpenClawAutomationsError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Automationen-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Automationen-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

struct OpenClawAutomationsClient {
    func automations() async throws -> AutomationsResponse {
        guard let baseURL = OpenClawSettings.automationsBaseURL, let token = OpenClawSettings.automationsToken else {
            throw OpenClawAutomationsError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/automations"))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw OpenClawAutomationsError.serverError(status: http.statusCode, message: String(data: data, encoding: .utf8) ?? "")
        }
        return try JSONDecoder().decode(AutomationsResponse.self, from: data)
    }
}
