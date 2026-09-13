import Foundation

/// Native on-device Live-Transkription (Apple Speech), umgezogen aus
/// `LocalServerController.swift` (Rest-Migrations-Plan, Abschnitt 3) - dieser
/// Code rief NIE das alte Python-Backend, sondern kompiliert/startet direkt
/// einen nativen Swift-Helfer aus dem gebuendelten `apple_speech.swift`, ganz
/// ohne HTTP/Python. Der Umzug ist rein strukturell (kein Verhaltensunterschied),
/// damit `LocalServerController.swift` am Ende komplett geloescht werden kann,
/// ohne dieses funktionierende Stueck mitzureissen.
enum LiveTranscriptionError: LocalizedError {
    case processFailed(String)

    var errorDescription: String? {
        switch self {
        case .processFailed(let message): message
        }
    }
}

final class LiveTranscriptionService {
    private let backendSourcePath = LiveTranscriptionService.detectBackendSourcePath()
    private let dataDirectory = LiveTranscriptionService.detectDataDirectory()

    /// Spawns the compiled `app/apple_speech` helper directly in `--live` mode - unlike
    /// `AppleSpeechEngine.listen_and_transcribe()` in app/stt_engines.py, which blocks on
    /// `subprocess.run(capture_output=True)` and therefore could never see partial results
    /// even after runLive() started emitting them, this goes straight from Swift to the
    /// compiled binary, bypassing Python entirely for this call path. Parses stderr via
    /// the existing `BridgeRuntimeEvent` parser (already understands the
    /// JarvisPartialTranscript:/JarvisFinalTranscript: lines runLive() emits) and forwards
    /// partials to `onPartial` as they arrive. Returns the final transcript - the single
    /// stdout line the process prints at exit - once it finishes.
    func startLiveTranscription(
        locale: String = "de-DE",
        onPartial: (@MainActor (String) -> Void)? = nil
    ) async throws -> String {
        try await ensureAppleSpeechHelperCompiled()

        let process = Process()
        process.executableURL = URL(fileURLWithPath: dataDirectory + "/apple_speech")
        process.arguments = ["--live", locale]
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        try process.run()

        let stderrReader = Task.detached { () -> String in
            let handle = stderrPipe.fileHandleForReading
            var buffer = Data()
            var fullText = ""
            while true {
                let data = handle.availableData
                if data.isEmpty { break }
                buffer.append(data)
                if let chunkText = String(data: data, encoding: .utf8) {
                    fullText += chunkText
                }
                while let newline = buffer.firstIndex(of: 10) {
                    let lineData = buffer[..<newline]
                    buffer.removeSubrange(...newline)
                    guard let line = String(data: lineData, encoding: .utf8) else { continue }
                    if let event = BridgeRuntimeEvent(line: line), case .partialTranscript(let text) = event {
                        await MainActor.run { onPartial?(text) }
                    }
                }
            }
            return fullText
        }

        // Same fix as LocalServerController's TTS bridge calls: read stdout and wait for
        // exit off the main thread, not directly here - this call runs up to ~14s (the
        // live-transcription window), and a blocking readDataToEndOfFile() on the main
        // thread for that long was confirmed to freeze the entire app UI (no clicks, no
        // redraws) for the whole duration.
        let (stdoutData, status): (Data, Int32) = await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let data = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                continuation.resume(returning: (data, process.terminationStatus))
            }
        }
        let stderrText = await stderrReader.value

        guard status == 0 else {
            throw LiveTranscriptionError.processFailed(stderrText.isEmpty ? "Live-Transkription fehlgeschlagen." : stderrText)
        }

        return String(data: stdoutData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    // KEEP IN SYNC: this is a byte-for-byte port of AppleSpeechEngine._ensure_helper() in
    // app/stt_engines.py:94-125 (same source/binary paths, same mtime comparison, same
    // swiftc invocation - module cache path and 120s timeout included). It exists because
    // startLiveTranscription() above launches the compiled binary directly from Swift,
    // bypassing the Python engine (and therefore Python's lazy-compile check) entirely.
    // If you change the compile logic here, change it there too.
    private func ensureAppleSpeechHelperCompiled() async throws {
        let sourceFile = backendSourcePath + "/app/apple_speech.swift"
        let binaryFile = dataDirectory + "/apple_speech"
        let fileManager = FileManager.default
        try? fileManager.createDirectory(atPath: dataDirectory, withIntermediateDirectories: true)

        guard fileManager.fileExists(atPath: sourceFile) else {
            throw LiveTranscriptionError.processFailed("Apple-Speech-Helper fehlt: \(sourceFile)")
        }

        func modificationDate(_ path: String) -> Date? {
            guard let attributes = try? fileManager.attributesOfItem(atPath: path) else { return nil }
            return attributes[.modificationDate] as? Date
        }

        var needsCompile = !fileManager.fileExists(atPath: binaryFile)
        if !needsCompile, let sourceDate = modificationDate(sourceFile), let binaryDate = modificationDate(binaryFile) {
            needsCompile = sourceDate > binaryDate
        }
        guard needsCompile else { return }

        let moduleCache = NSTemporaryDirectory() + "jarvis_swift_module_cache"
        try? fileManager.createDirectory(atPath: moduleCache, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["swiftc", "-module-cache-path", moduleCache, sourceFile, "-o", binaryFile]
        let stderrPipe = Pipe()
        process.standardOutput = Pipe()
        process.standardError = stderrPipe

        try process.run()

        let timedOut = await withTaskGroup(of: Bool.self) { group -> Bool in
            group.addTask {
                await withCheckedContinuation { continuation in
                    DispatchQueue.global(qos: .userInitiated).async {
                        process.waitUntilExit()
                        continuation.resume(returning: false)
                    }
                }
            }
            group.addTask {
                try? await Task.sleep(for: .seconds(120))
                return true
            }
            let result = await group.next() ?? false
            group.cancelAll()
            return result
        }

        if timedOut {
            process.terminate()
            throw LiveTranscriptionError.processFailed("Apple-Speech-Helper Kompilierung hat zu lange gedauert.")
        }

        guard process.terminationStatus == 0 else {
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errorText = String(data: errorData, encoding: .utf8) ?? ""
            throw LiveTranscriptionError.processFailed(errorText.isEmpty ? "Apple-Speech-Helper konnte nicht kompiliert werden." : "Apple-Speech-Helper konnte nicht kompiliert werden: \(errorText)")
        }
    }

    /// Identische Erkennungslogik wie LocalServerController.detectBackendSourcePath() -
    /// bewusst dupliziert statt geteilt, damit dieser Dienst unabhaengig vom (spaeter
    /// entfernten) LocalServerController funktioniert.
    private static func detectBackendSourcePath() -> String {
        let fileManager = FileManager.default

        if let resourcePath = Bundle.main.resourcePath {
            let bundled = resourcePath + "/JarvisBackend"
            if fileManager.fileExists(atPath: bundled + "/app/jarvis.py") {
                return bundled
            }
        }

        var candidates: [URL] = []
        let sourceFile = URL(fileURLWithPath: #filePath)
        candidates.append(sourceFile)
        candidates.append(URL(fileURLWithPath: fileManager.currentDirectoryPath))
        candidates.append(Bundle.main.bundleURL)
        candidates.append(fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Desktop/JARVIS-OS"))

        for candidate in candidates {
            var current = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            for _ in 0..<12 {
                if fileManager.fileExists(atPath: current.appendingPathComponent("app/jarvis.py").path) {
                    return current.path
                }
                let parent = current.deletingLastPathComponent()
                if parent.path == current.path { break }
                current = parent
            }
        }

        return fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Desktop/JARVIS-OS").path
    }

    private static func detectDataDirectory() -> String {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let identifier = Bundle.main.bundleIdentifier ?? "com.leon.jarvis"
        return base.appendingPathComponent(identifier).path
    }
}
