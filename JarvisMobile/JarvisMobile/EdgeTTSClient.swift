import Foundation

/// Fetches Edge-TTS-synthesized speech (same German neural voice the old
/// JARVIS-OS Mac project used, config.json: edge_voice "de-DE-KillianNeural")
/// from the Mac Mini's small standalone TTS proxy (scripts/tts_proxy_server.py)
/// instead of talking to Microsoft directly.
///
/// A first version of this reimplemented Microsoft's unofficial Edge-TTS
/// WebSocket protocol directly in Swift (no Mac Mini round-trip at all) - live
/// tested 2026-09-08 and blocked by a new bot-detection layer (HTTP 403 +
/// a Client-Hints challenge only a real browser can satisfy). Rather than
/// escalate into spoofing more of a browser fingerprint to defeat that check,
/// the user chose to route through a small Mac-Mini-side proxy that uses the
/// actively-maintained Python `edge_tts` library instead (same one the old
/// backend already used, app/voice_output.py) - it gets updated when
/// Microsoft changes something, this hand-rolled client wouldn't have.
/// Playback still happens locally on the iPhone (VoiceManager.playEdgeAudio) -
/// only the synthesis step round-trips to the Mac Mini.
enum EdgeTTSError: LocalizedError {
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

enum EdgeTTS {
    /// Synthesizes `text` via the Mac Mini's TTS proxy and returns raw MP3
    /// bytes. Throws if not paired/no token, or on any network/server error -
    /// callers should fall back to a local TTS engine.
    static func synthesize(
        text: String,
        voice: String,
        rate: String = "+0%",
        pitch: String = "+0Hz",
        volume: String = "+0%"
    ) async throws -> Data {
        guard let baseURL = RemoteSettings.ttsBaseURL, let token = RemoteSettings.ttsToken else {
            throw EdgeTTSError.notPaired
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
            throw EdgeTTSError.serverError(status: -1, message: "Keine HTTP-Antwort erhalten.")
        }
        guard httpResponse.statusCode == 200 else {
            let message = String(data: data, encoding: .utf8) ?? "unbekannt"
            throw EdgeTTSError.serverError(status: httpResponse.statusCode, message: message)
        }
        return data
    }
}
