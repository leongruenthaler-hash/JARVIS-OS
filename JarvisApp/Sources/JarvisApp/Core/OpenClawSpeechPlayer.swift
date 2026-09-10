import Foundation
import AVFoundation

/// Replaces both `EdgeTTSService` and `StreamingSpeechPlayer` (2026-09-10) - synthesizes
/// via the Mac Mini's TTS proxy (OpenClawTTSClient, same Killian voice JarvisMobile uses)
/// instead of the old backend's tts_bridge.py, and plays locally via AVAudioPlayer instead
/// of `LocalServerController.playSpeechFile`. Structurally a direct port of
/// StreamingSpeechPlayer's depth-1 prefetch pipeline (same reasoning: play the current
/// sentence while the next one synthesizes in the background) plus the simple
/// `TTSService.speak(_:)` single-shot path, combined into one type since both now share
/// the same synth+play primitives.
@MainActor
final class OpenClawSpeechPlayer: NSObject, TTSService {
    var onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?

    private var audioPlayer: AVAudioPlayer?
    private var playbackContinuation: CheckedContinuation<Void, Never>?

    private var pendingSentences: [String] = []
    private var doneEnqueuing = false
    private var isCancelled = false
    private var driveTask: Task<Void, Never>?

    // MARK: - TTSService (single-shot, e.g. greetings)

    func speak(_ text: String) async throws {
        try await speak(text, onEvent: nil)
    }

    func speak(_ text: String, onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?) async throws {
        onEvent?(.ttsStarted)
        let audioData = try await OpenClawTTS.synthesize(text: text)
        onEvent?(.audioPlaybackStarted)
        await play(audioData)
        onEvent?(.ttsFinished)
    }

    func stop() async {
        await cancel()
    }

    // MARK: - Sentence-pipelined (StreamingSpeechPlayer's API, unchanged for AppState)

    /// Adds a completed sentence to the queue and starts the playback loop if it isn't
    /// already running. Safe to call repeatedly while earlier sentences are still playing.
    func enqueue(_ sentence: String) {
        let trimmed = sentence.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isCancelled else { return }
        pendingSentences.append(trimmed)
        startDrivingIfNeeded()
    }

    /// Call once every sentence has been enqueued. Waits until playback fully finishes.
    func finish() async {
        doneEnqueuing = true
        startDrivingIfNeeded()
        await driveTask?.value
    }

    /// Stops playback immediately and abandons any not-yet-played queued sentences.
    func cancel() async {
        isCancelled = true
        doneEnqueuing = true
        pendingSentences.removeAll()
        audioPlayer?.stop()
        audioPlayer = nil
        playbackContinuation?.resume()
        playbackContinuation = nil
        await driveTask?.value
    }

    private func startDrivingIfNeeded() {
        guard driveTask == nil else { return }
        driveTask = Task { [weak self] in
            await self?.drive()
        }
    }

    private func drive() async {
        var hasStarted = false
        var prefetchTask: Task<Data?, Never>?
        var prefetchSentence: String?

        while !isCancelled {
            let audioData: Data?

            if let task = prefetchTask, prefetchSentence != nil {
                audioData = await task.value
                prefetchTask = nil
                prefetchSentence = nil
            } else if !pendingSentences.isEmpty {
                let sentence = pendingSentences.removeFirst()
                if !hasStarted { onEvent?(.ttsStarted); hasStarted = true }
                audioData = try? await OpenClawTTS.synthesize(text: sentence)
            } else if doneEnqueuing {
                break
            } else {
                try? await Task.sleep(for: .milliseconds(50))
                continue
            }

            if isCancelled { break }

            // Start prefetching the NEXT sentence now, concurrently with this one's playback.
            if prefetchTask == nil, !pendingSentences.isEmpty {
                let next = pendingSentences.removeFirst()
                prefetchSentence = next
                prefetchTask = Task { try? await OpenClawTTS.synthesize(text: next) }
            }

            if let audioData {
                onEvent?(.audioPlaybackStarted)
                await play(audioData)
            }
        }

        onEvent?(.ttsFinished)
        driveTask = nil
    }

    private func play(_ data: Data) async {
        await withCheckedContinuation { continuation in
            guard let player = try? AVAudioPlayer(data: data) else {
                continuation.resume()
                return
            }
            player.delegate = self
            audioPlayer = player
            playbackContinuation = continuation
            guard player.play() else {
                audioPlayer = nil
                playbackContinuation = nil
                continuation.resume()
                return
            }
        }
    }
}

extension OpenClawSpeechPlayer: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.audioPlayer = nil
            self.playbackContinuation?.resume()
            self.playbackContinuation = nil
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in
            self.audioPlayer = nil
            self.playbackContinuation?.resume()
            self.playbackContinuation = nil
        }
    }
}
