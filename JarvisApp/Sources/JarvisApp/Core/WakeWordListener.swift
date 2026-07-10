import Foundation
import Speech

/// Kurze, rein lokale On-Device-Spracherkennung + Fuzzy-Wake-Word-Check fuer den
/// Immer-Zuhoer-Modus. Die eigentliche Audio-Aufnahme (Pegel-Erkennung, isSpeaking-Guard)
/// laeuft ueber das bereits bestehende AudioCaptureService.recordUtterance() - dieser Typ
/// nimmt nur die kurze, dabei entstandene WAV-Datei und prueft, ob "Jarvis" drin vorkam.
@MainActor
final class WakeWordListener {
    enum WakeWordError: LocalizedError {
        case permissionDenied
        case recognizerUnavailable
        case recognitionFailed(String)

        var errorDescription: String? {
            switch self {
            case .permissionDenied:
                return "Spracherkennungszugriff fehlt."
            case .recognizerUnavailable:
                return "Die lokale Spracherkennung ist gerade nicht verfügbar."
            case .recognitionFailed(let message):
                return message
            }
        }
    }

    // Spiegelt die Fuzzy-Wake-Word-Logik aus app/jarvis.py (remove_wake_word()/_looks_like_wake_word()).
    // Bei Aenderungen dort (z.B. neues Alias-Wort, andere Distanz) bitte auch hier nachziehen.
    private static let wakeWordAliases: Set<String> = [
        "jarvis", "javis", "jarves", "jarvice", "jarvies", "jarvisse",
        "jathers", "jaros", "jarus", "trabbers", "jobs", "john", "thomas",
    ]
    private static let wakeWordCandidates = ["jarvis", "javis", "jaros", "jarus", "jathers", "trabbers"]
    private static let wakeWordFalsePositives: Set<String> = ["warum", "darum", "jargon"]

    private let locale: String

    init(locale: String = "de-DE") {
        self.locale = locale
    }

    func requestPermissionIfNeeded() async -> Bool {
        let current = SFSpeechRecognizer.authorizationStatus()
        if current == .authorized {
            return true
        }
        if current == .denied || current == .restricted {
            return false
        }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    /// Transkribiert eine kurze, bereits aufgenommene Audiodatei rein lokal auf dem Geraet.
    func transcribeOnDevice(fileURL: URL) async throws -> String {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale)), recognizer.isAvailable else {
            throw WakeWordError.recognizerUnavailable
        }

        let request = SFSpeechURLRecognitionRequest(url: fileURL)
        request.shouldReportPartialResults = false
        request.requiresOnDeviceRecognition = true

        return try await withCheckedThrowingContinuation { continuation in
            var didResume = false
            let task = recognizer.recognitionTask(with: request) { result, error in
                guard !didResume else { return }
                if let error {
                    didResume = true
                    continuation.resume(throwing: WakeWordError.recognitionFailed(error.localizedDescription))
                    return
                }
                if let result, result.isFinal {
                    didResume = true
                    continuation.resume(returning: result.bestTranscription.formattedString)
                }
            }
            _ = task
        }
    }

    static func containsWakeWord(_ text: String) -> Bool {
        let normalized = text
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()

        let words = normalized
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }

        for word in words {
            if wakeWordAliases.contains(word) || looksLikeWakeWord(word) {
                return true
            }
        }
        return false
    }

    private static func looksLikeWakeWord(_ word: String) -> Bool {
        guard word.count >= 4 else { return false }
        if wakeWordFalsePositives.contains(word) { return false }
        return wakeWordCandidates.contains { levenshteinDistance($0, word) <= 2 }
    }

    private static func levenshteinDistance(_ lhs: String, _ rhs: String) -> Int {
        let a = Array(lhs)
        let b = Array(rhs)
        if a.isEmpty { return b.count }
        if b.isEmpty { return a.count }

        var previousRow = Array(0...b.count)
        var currentRow = [Int](repeating: 0, count: b.count + 1)

        for i in 1...a.count {
            currentRow[0] = i
            for j in 1...b.count {
                let cost = a[i - 1] == b[j - 1] ? 0 : 1
                currentRow[j] = min(
                    previousRow[j] + 1,
                    currentRow[j - 1] + 1,
                    previousRow[j - 1] + cost
                )
            }
            previousRow = currentRow
        }
        return previousRow[b.count]
    }
}
