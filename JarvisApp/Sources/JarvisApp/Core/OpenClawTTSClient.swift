import Foundation

/// Fetches Edge-TTS-synthesized speech (de-DE-KillianNeural) from the Mac Mini's small
/// standalone TTS proxy (scripts/tts_proxy_server.py) - direct port of JarvisMobile's
/// EdgeTTSClient.swift. Same proxy, same voice, same reasoning: Microsoft's Edge-TTS
/// blocks unofficial direct clients (bot detection), so this round-trips through the
/// actively-maintained Python `edge_tts` library on the Mac Mini instead.
enum OpenClawTTSError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein TTS-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "TTS-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

enum OpenClawTTS {
    static let voice = "de-DE-KillianNeural"

    static func synthesize(
        text: String,
        voice: String = OpenClawTTS.voice,
        rate: String = "+0%",
        pitch: String = "+0Hz",
        volume: String = "+0%"
    ) async throws -> Data {
        guard let baseURL = OpenClawSettings.ttsBaseURL, let token = OpenClawSettings.ttsToken else {
            throw OpenClawTTSError.notPaired
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("tts"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "text": text,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "volume": volume,
        ])
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw OpenClawTTSError.serverError(status: -1, message: "Keine HTTP-Antwort erhalten.")
        }
        guard httpResponse.statusCode == 200 else {
            let message = String(data: data, encoding: .utf8) ?? "unbekannt"
            throw OpenClawTTSError.serverError(status: httpResponse.statusCode, message: message)
        }
        return data
    }
}
