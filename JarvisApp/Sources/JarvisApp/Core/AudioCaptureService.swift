import AVFoundation
import Foundation

struct AudioCaptureResult {
    let fileURL: URL
    let sampleRate: Double
    let duration: TimeInterval
    let speechDuration: TimeInterval
    let meanVolume: Double
    let peakVolume: Double
}

@MainActor
final class AudioCaptureService {
    enum CaptureError: LocalizedError {
        case permissionDenied
        case recorderUnavailable
        case noSpeechDetected
        case cancelled
        case recorderFailed(String)

        var errorDescription: String? {
            switch self {
            case .permissionDenied:
                return "Mikrofonzugriff fehlt."
            case .recorderUnavailable:
                return "Der Audio-Recorder konnte nicht gestartet werden."
            case .noSpeechDetected:
                return "Es wurde keine Sprache erkannt."
            case .cancelled:
                return "Die Aufnahme wurde abgebrochen."
            case .recorderFailed(let message):
                return message
            }
        }
    }

    private let recordPermissionKey = "JarvisAudioCapturePermissionChecked"
    private var currentRecorder: AVAudioRecorder?
    private var currentFileURL: URL?
    private var stopRequested = false

    func prepareAudioSession() async {
        _ = UserDefaults.standard.bool(forKey: recordPermissionKey)
    }

    func requestPermissionIfNeeded() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        switch status {
        case .authorized:
            UserDefaults.standard.set(true, forKey: recordPermissionKey)
            return true
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    UserDefaults.standard.set(granted, forKey: self.recordPermissionKey)
                    continuation.resume(returning: granted)
                }
            }
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }

    func cancel() {
        stopRequested = true
        currentRecorder?.stop()
        currentRecorder = nil
        currentFileURL = nil
    }

    func recordUtterance(
        maxDuration: TimeInterval = 10,
        silenceLimit: TimeInterval = 0.9,
        minSpeechDuration: TimeInterval = 0.45,
        maxWaitForSpeech: TimeInterval = 8.0,
        sampleRate: Double = 16_000,
        threshold: Double = 0.010,
        isSpeaking: (() -> Bool)? = nil,
        onUpdate: (@MainActor (_ level: Double, _ speechDetected: Bool) -> Void)? = nil
    ) async throws -> AudioCaptureResult {
        if stopRequested {
            stopRequested = false
            throw CaptureError.cancelled
        }

        guard await requestPermissionIfNeeded() else {
            throw CaptureError.permissionDenied
        }

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("jarvis_voice_\(UUID().uuidString).wav")
        currentFileURL = fileURL

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        let recorder: AVAudioRecorder
        do {
            recorder = try AVAudioRecorder(url: fileURL, settings: settings)
        } catch {
            throw CaptureError.recorderFailed(error.localizedDescription)
        }

        recorder.isMeteringEnabled = true
        recorder.prepareToRecord()
        guard recorder.record() else {
            throw CaptureError.recorderUnavailable
        }

        currentRecorder = recorder
        onUpdate?(0, false)
        let startedAt = Date()
        var speechStartedAt: Date?
        var lastSpeechAt: Date?
        var speechDuration: TimeInterval = 0
        var meanAccumulator: Double = 0
        var peakVolume: Double = 0
        var sampleCount = 0
        var lastLevel: Double = 0

        defer {
            recorder.stop()
            currentRecorder = nil
            currentFileURL = nil
        }

        while !Task.isCancelled && !stopRequested {
            try await Task.sleep(for: .milliseconds(50))
            recorder.updateMeters()

            if isSpeaking?() == true {
                speechStartedAt = nil
                lastSpeechAt = nil
                speechDuration = 0
                meanAccumulator = 0
                sampleCount = 0
                peakVolume = 0
                onUpdate?(0, false)
                continue
            }

            let level = max(-160.0, Double(recorder.averagePower(forChannel: 0)))
            let normalized = Self.normalizedLevel(fromDecibels: level)
            meanAccumulator += normalized
            sampleCount += 1
            peakVolume = max(peakVolume, normalized)
            lastLevel = normalized

            let speechDetected = normalized >= threshold
            onUpdate?(normalized, speechDetected)
            if speechDetected {
                if speechStartedAt == nil {
                    speechStartedAt = Date()
                }
                lastSpeechAt = Date()
                speechDuration = Date().timeIntervalSince(speechStartedAt ?? Date())
            }

            let elapsed = Date().timeIntervalSince(startedAt)
            if speechStartedAt == nil {
                if elapsed >= maxWaitForSpeech {
                    throw CaptureError.noSpeechDetected
                }
                continue
            }

            if let lastSpeechAt {
                let silence = Date().timeIntervalSince(lastSpeechAt)
                if speechDuration >= minSpeechDuration && silence >= silenceLimit {
                    break
                }
            }

            if elapsed >= maxDuration {
                break
            }
        }

        if stopRequested {
            stopRequested = false
            throw CaptureError.cancelled
        }

        let fileSize = (try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber)?.doubleValue ?? 0
        if fileSize <= 0 {
            throw CaptureError.noSpeechDetected
        }

        stopRequested = false
        return AudioCaptureResult(
            fileURL: fileURL,
            sampleRate: sampleRate,
            duration: Date().timeIntervalSince(startedAt),
            speechDuration: max(speechDuration, 0),
            meanVolume: sampleCount > 0 ? meanAccumulator / Double(sampleCount) : lastLevel,
            peakVolume: peakVolume
        )
    }

    private static func normalizedLevel(fromDecibels decibels: Double) -> Double {
        if decibels <= -80 { return 0 }
        return pow(10.0, decibels / 20.0)
    }
}
