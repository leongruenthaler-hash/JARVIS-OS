import Foundation

/// Speaks sentences as they become available from a live-streaming chat answer, using a
/// depth-1 prefetch pipeline: while the current sentence plays, the next one is already
/// being synthesized in the background, so there's ideally no gap between them. The very
/// first sentence has no prior playback to overlap with, so its synthesis is unavoidably
/// on the critical path - every sentence after that should start near-instantly.
///
/// Falls back to `LocalServerController.speakText` (the original combined synth+play call)
/// per sentence whenever synthesis fails (e.g. `tts_provider` isn't "edge") - degrades to
/// the old sequential behavior for that sentence instead of losing audio.
@MainActor
final class StreamingSpeechPlayer {
    private let controller: LocalServerController
    var onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?

    private var pendingSentences: [String] = []
    private var doneEnqueuing = false
    private var isCancelled = false
    private var driveTask: Task<Void, Never>?

    init(controller: LocalServerController) {
        self.controller = controller
    }

    /// Adds a completed sentence to the queue and starts the playback loop if it isn't
    /// already running. Safe to call repeatedly while earlier sentences are still playing.
    func enqueue(_ sentence: String) {
        let trimmed = sentence.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isCancelled else { return }
        pendingSentences.append(trimmed)
        startDrivingIfNeeded()
    }

    /// Call once the source text stream is fully done (all sentences enqueued). Waits
    /// until every enqueued sentence has finished playing.
    func finish() async {
        doneEnqueuing = true
        startDrivingIfNeeded()
        await driveTask?.value
    }

    /// Stops playback immediately and abandons any not-yet-played queued sentences and
    /// in-flight prefetch synthesis.
    func cancel() async {
        isCancelled = true
        doneEnqueuing = true
        pendingSentences.removeAll()
        await controller.cancelPendingSynthesis()
        await controller.stopSpeaking()
        await driveTask?.value
    }

    private func startDrivingIfNeeded() {
        guard driveTask == nil else { return }
        driveTask = Task { [weak self] in
            await self?.drive()
        }
    }

    private func drive() async {
        var prefetchTask: Task<(sentence: String, audioFile: String)?, Never>?
        var prefetchSentence: String?

        while !isCancelled {
            let sentence: String
            let audioFile: String?

            if let task = prefetchTask, let expected = prefetchSentence {
                let result = await task.value
                prefetchTask = nil
                prefetchSentence = nil
                sentence = expected
                audioFile = result?.audioFile
            } else if !pendingSentences.isEmpty {
                sentence = pendingSentences.removeFirst()
                audioFile = try? await controller.synthesizeSpeech(sentence, onEvent: onEvent)
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
                prefetchTask = Task { [weak self] in
                    guard let self else { return nil }
                    guard let file = try? await self.controller.synthesizeSpeech(next, onEvent: self.onEvent) else {
                        return nil
                    }
                    return (next, file)
                }
            }

            if let audioFile {
                try? await controller.playSpeechFile(audioFile, onEvent: onEvent)
            } else {
                try? await controller.speakText(sentence, onEvent: onEvent)
            }
        }

        driveTask = nil
    }
}
