import Foundation

/// Parses the stderr lines emitted by native Swift helper subprocesses (e.g.
/// `apple_speech --live`, launched directly by `LiveTranscriptionService`) into typed
/// voice-pipeline events. Relocated out of the now-deleted `LocalServerController.swift`
/// (Rest-Migrations-Plan, Abschnitt 8) - this parser itself never depended on the old
/// Python backend, only on the line-based event convention the bundled Swift helpers use.
enum BridgeRuntimeEvent {
    case microphoneReady
    case recordingStarted
    case userSpeechDetected
    case recordingStopped
    case transcribedText
    case transcriptionDone
    case llmResponseStarted
    case llmResponseFinished
    case assistantResponse
    case ttsStarted
    case audioPlaybackStarted
    case ttsFinished
    case ttsSynthesizeStarted
    case ttsSynthesizeFinished
    case assistantDelta(String)
    case partialTranscript(String)
    case finalTranscript(String)

    init?(line: String) {
        let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("JarvisStreamChunk:") {
            let jsonText = text.replacingOccurrences(of: "JarvisStreamChunk:", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            if let data = jsonText.data(using: .utf8),
               let payload = try? JSONDecoder().decode(BridgeStreamChunk.self, from: data) {
                self = .assistantDelta(payload.chunk)
                return
            }
            return nil
        } else if text.hasPrefix("JarvisPartialTranscript:") {
            let jsonText = text.replacingOccurrences(of: "JarvisPartialTranscript:", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            if let data = jsonText.data(using: .utf8),
               let payload = try? JSONDecoder().decode(BridgeTranscriptPayload.self, from: data) {
                self = .partialTranscript(payload.text)
                return
            }
            return nil
        } else if text.hasPrefix("JarvisFinalTranscript:") {
            let jsonText = text.replacingOccurrences(of: "JarvisFinalTranscript:", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            if let data = jsonText.data(using: .utf8),
               let payload = try? JSONDecoder().decode(BridgeTranscriptPayload.self, from: data) {
                self = .finalTranscript(payload.text)
                return
            }
            return nil
        } else if text.contains("VoicePerformanceEvent: microphoneReady") || text.contains("Jarvis hört zu") {
            self = .microphoneReady
        } else if text.contains("VoicePerformanceEvent: recordingStarted") {
            self = .recordingStarted
        } else if text.contains("Sprache erkannt") {
            self = .userSpeechDetected
        } else if text.contains("VoicePerformanceEvent: recordingStopped") || text.contains("Satz abgeschlossen") || text.hasPrefix("Audio:") {
            self = .recordingStopped
        } else if text.contains("VoicePerformanceEvent: transcriptionDone") {
            self = .transcriptionDone
        } else if text.contains("VoicePerformanceEvent: llmResponseStarted") {
            self = .llmResponseStarted
        } else if text.contains("VoicePerformanceEvent: firstLLMToken") {
            self = .assistantResponse
        } else if text.contains("VoicePerformanceEvent: llmResponseFinished") {
            self = .llmResponseFinished
        } else if text.contains("Pipeline: transcribedText") {
            self = .transcribedText
        } else if text.contains("Pipeline: assistantResponse") {
            self = .assistantResponse
        } else if text.contains("VoicePerformanceEvent: ttsStarted") {
            self = .ttsStarted
        } else if text.contains("VoicePerformanceEvent: audioPlaybackStarted") {
            self = .audioPlaybackStarted
        } else if text.contains("VoicePerformanceEvent: ttsFinished") {
            self = .ttsFinished
        } else if text.contains("VoicePerformanceEvent: ttsSynthesizeStarted") {
            self = .ttsSynthesizeStarted
        } else if text.contains("VoicePerformanceEvent: ttsSynthesizeFinished") {
            self = .ttsSynthesizeFinished
        } else {
            return nil
        }
    }
}

private struct BridgeStreamChunk: Decodable {
    let chunk: String
}

private struct BridgeTranscriptPayload: Decodable {
    let text: String
}
