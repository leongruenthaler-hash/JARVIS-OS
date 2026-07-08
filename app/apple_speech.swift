import AVFoundation
import Foundation
import Speech

let arguments = CommandLine.arguments

func fail(_ message: String, _ code: Int32) -> Never {
    fputs(message + "\n", stderr)
    exit(code)
}

func requestSpeechPermission() {
    let currentStatus = SFSpeechRecognizer.authorizationStatus()
    if currentStatus == .authorized {
        return
    }

    let semaphore = DispatchSemaphore(value: 0)
    var status: SFSpeechRecognizerAuthorizationStatus = .notDetermined

    SFSpeechRecognizer.requestAuthorization { newStatus in
        status = newStatus
        semaphore.signal()
    }

    _ = semaphore.wait(timeout: .now() + 10)

    guard status == .authorized else {
        fail("Apple Speech permission is not authorized. Status: \(status.rawValue)", 4)
    }
}

func requestMicrophonePermission() {
    let currentStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    if currentStatus == .authorized {
        return
    }

    let semaphore = DispatchSemaphore(value: 0)
    var granted = false

    AVCaptureDevice.requestAccess(for: .audio) { isGranted in
        granted = isGranted
        semaphore.signal()
    }

    _ = semaphore.wait(timeout: .now() + 10)

    guard granted else {
        fail("Microphone permission is not authorized.", 7)
    }
}

func makeRecognizer(localeIdentifier: String) -> SFSpeechRecognizer {
    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)) else {
        fail("Apple Speech recognizer is not available for locale \(localeIdentifier).", 3)
    }

    guard recognizer.isAvailable else {
        fail("Apple Speech recognizer is currently not available.", 8)
    }

    return recognizer
}

func runLive(localeIdentifier: String) {
    requestSpeechPermission()
    requestMicrophonePermission()

    let recognizer = makeRecognizer(localeIdentifier: localeIdentifier)
    let audioEngine = AVAudioEngine()
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = true

    if #available(macOS 10.15, *) {
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
    }

    var finalText = ""
    var lastPartialText = ""
    var finalError: Error?
    var hasSpeech = false
    var lastSpeechTime = Date()
    var lastLevelLogTime = Date()
    var peakMean: Float = 0
    let maxDuration: TimeInterval = 14.0
    let silenceLimit: TimeInterval = 1.0
    let volumeThreshold: Float = 0.006
    let startTime = Date()
    let doneSemaphore = DispatchSemaphore(value: 0)

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result = result {
            lastPartialText = result.bestTranscription.formattedString
            if result.isFinal && !result.bestTranscription.formattedString.isEmpty {
                finalText = result.bestTranscription.formattedString
                doneSemaphore.signal()
            }
        }

        if let error = error {
            finalError = error
            if hasSpeech {
                doneSemaphore.signal()
            }
        }
    }

    let inputNode = audioEngine.inputNode
    let format = inputNode.outputFormat(forBus: 0)

    inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
        request.append(buffer)

        guard let channel = buffer.floatChannelData?[0] else {
            return
        }

        let frameCount = Int(buffer.frameLength)
        if frameCount == 0 {
            return
        }

        var sum: Float = 0
        for index in 0..<frameCount {
            sum += abs(channel[index])
        }

        let mean = sum / Float(frameCount)
        if mean > peakMean {
            peakMean = mean
        }

        if Date().timeIntervalSince(lastLevelLogTime) >= 2.0 && !hasSpeech {
            fputs(String(format: "Apple Speech Mikrofonpegel: Mean=%.4f | PeakMean=%.4f | Schwelle=%.4f\n", mean, peakMean, volumeThreshold), stderr)
            lastLevelLogTime = Date()
        }

        if mean >= volumeThreshold {
            if !hasSpeech {
                fputs(String(format: "Apple Speech Sprache erkannt: Mean=%.4f | Schwelle=%.4f\n", mean, volumeThreshold), stderr)
            }
            hasSpeech = true
            lastSpeechTime = Date()
        }
    }

    do {
        audioEngine.prepare()
        try audioEngine.start()
    } catch {
        task.cancel()
        fail("Audio engine could not start: \(error.localizedDescription)", 9)
    }

    while true {
        Thread.sleep(forTimeInterval: 0.05)

        if doneSemaphore.wait(timeout: .now()) == .success && (!finalText.isEmpty || !lastPartialText.isEmpty) {
            break
        }

        if hasSpeech && Date().timeIntervalSince(lastSpeechTime) >= silenceLimit {
            break
        }

        if Date().timeIntervalSince(startTime) >= maxDuration {
            break
        }
    }

    audioEngine.stop()
    inputNode.removeTap(onBus: 0)
    request.endAudio()

    _ = doneSemaphore.wait(timeout: .now() + 2.0)
    task.cancel()

    if let error = finalError, finalText.isEmpty && lastPartialText.isEmpty {
        fail("Apple Speech failed: \(error.localizedDescription)", 6)
    }

    let output = finalText.isEmpty ? lastPartialText : finalText
    if output.isEmpty && !hasSpeech {
        fputs("Apple Speech hat keine Sprache erkannt.\n", stderr)
    }
    print(output)
}

func runFile(audioPath: String, localeIdentifier: String) {
    requestSpeechPermission()

    let recognizer = makeRecognizer(localeIdentifier: localeIdentifier)
    let audioURL = URL(fileURLWithPath: audioPath)
    let request = SFSpeechURLRecognitionRequest(url: audioURL)
    request.shouldReportPartialResults = false

    if #available(macOS 10.15, *) {
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
    }

    let semaphore = DispatchSemaphore(value: 0)
    var finalText = ""
    var finalError: Error?

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result = result {
            finalText = result.bestTranscription.formattedString
            if result.isFinal {
                semaphore.signal()
            }
        }

        if let error = error {
            finalError = error
            semaphore.signal()
        }
    }

    let waitResult = semaphore.wait(timeout: .now() + 20)
    task.cancel()

    if waitResult == .timedOut {
        fail("Apple Speech timed out.", 5)
    }

    if let error = finalError, finalText.isEmpty {
        fail("Apple Speech failed: \(error.localizedDescription)", 6)
    }

    print(finalText)
}

if arguments.count >= 2 && arguments[1] == "--live" {
    let localeIdentifier = arguments.count >= 3 ? arguments[2] : "de-DE"
    runLive(localeIdentifier: localeIdentifier)
} else if arguments.count >= 2 {
    let audioPath = arguments[1]
    let localeIdentifier = arguments.count >= 3 ? arguments[2] : "de-DE"
    runFile(audioPath: audioPath, localeIdentifier: localeIdentifier)
} else {
    fail("Usage: apple_speech --live [locale] OR apple_speech <audio-file.wav> [locale]", 2)
}
