import Foundation

/// Transcribes a recorded voice-message WAV file via the Mac Mini's small standalone
/// Sprachnachrichten-Transkriptions-Proxy (scripts/voice_transcribe_proxy_server.py) -
/// replaces the old backend's `/api/voice/transcribe`, which expected a LOCAL file path
/// on the same machine as the server and stopped working once JarvisApp became a pure
/// remote client (Rest-Migrations-Plan, Abschnitt 3). Same reasoning/shape as
/// `OpenClawTTSClient.swift`: a narrow, single-purpose proxy instead of reviving the
/// whole old backend, chosen over switching to on-device Apple Speech so the existing
/// STT accuracy (faster-whisper/whisper-4bit/moonshine, whichever the Mac Mini has
/// installed - see app/stt_engines.py::create_stt_engine) is preserved.
enum VoiceTranscribeError: LocalizedError {
    case notPaired
    case serverError(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Transkriptions-Proxy-Token hinterlegt."
        case .serverError(let status, let message):
            return "Transkriptions-Proxy-Fehler (\(status)): \(message)"
        }
    }
}

enum VoiceTranscribeClient {
    static func transcribe(audioPath: String, sampleRate: Double) async throws -> String {
        guard let baseURL = OpenClawSettings.voiceTranscribeBaseURL, let token = OpenClawSettings.voiceTranscribeToken else {
            throw VoiceTranscribeError.notPaired
        }

        let audioData = try Data(contentsOf: URL(fileURLWithPath: audioPath))

        var request = URLRequest(url: baseURL.appendingPathComponent("api/voice/transcribe"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "audio_base64": audioData.base64EncodedString(),
            "sample_rate": sampleRate,
        ])
        request.timeoutInterval = 30

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw VoiceTranscribeError.serverError(status: -1, message: "Keine HTTP-Antwort erhalten.")
        }
        guard httpResponse.statusCode == 200 else {
            let message = String(data: data, encoding: .utf8) ?? "unbekannt"
            throw VoiceTranscribeError.serverError(status: httpResponse.statusCode, message: message)
        }

        struct Response: Decodable { let text: String }
        let decoded = try JSONDecoder().decode(Response.self, from: data)
        return decoded.text
    }
}
