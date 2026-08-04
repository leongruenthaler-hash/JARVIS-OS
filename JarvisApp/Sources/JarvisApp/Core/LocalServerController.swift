import Foundation

@MainActor
final class LocalServerController: ObservableObject {
    @Published var isRunning = false
    @Published var lastLaunchError: String?

    private static let startLogPath = "/tmp/jarvis_app_server_start.log"
    private static let bundledOllamaPort = 11500
    private static let bootstrapStatusPath = "/tmp/jarvis_app_bootstrap_status.txt"
    private static let voiceBootstrapStatusPath = "/tmp/jarvis_app_voice_bootstrap_status.txt"

    /// Read-only: where `app/` (the Python source) lives. Either the bundled,
    /// signed-app copy (`Contents/Resources/JarvisBackend`) or, for developers running
    /// from a source checkout, the live `app/` folder next to `.git`.
    private let backendSourcePath = LocalServerController.detectBackendSourcePath()
    /// Writable: where the venv, memory, cache, config, and compiled helper binaries
    /// live - never inside the (potentially read-only, code-signed) app bundle.
    private let dataDirectory = LocalServerController.detectDataDirectory()
    private var venvPath: String { dataDirectory + "/venv" }

    private let apiClient = JarvisAPIClient()
    private var serverProcess: Process?
    private var ttsProcess: Process?
    private var synthesizeProcess: Process?
    private var warmupProcess: Process?

    var hasOwnedProcess: Bool { serverProcess != nil }

    /// Whether the Python backend's venv has already been set up. `false` on a fresh
    /// install where `start()` will need to bootstrap it first (slow: several minutes).
    var venvPythonExists: Bool {
        FileManager.default.fileExists(atPath: venvPath + "/bin/python3")
    }

    /// Merges `JARVIS_DATA_DIR` into the current environment for subprocesses that
    /// invoke `.venv/bin/python3` outside of `start()`'s own script (which exports it
    /// itself before the final `exec`). Each of these spawns its own independent
    /// `Process()`, so this has to be set explicitly at every one of them.
    private func pythonEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["JARVIS_DATA_DIR"] = dataDirectory
        return env
    }

    struct BootstrapStatus {
        let stage: String
        let message: String
    }

    /// Reads the progress line the bootstrap script in `start()` writes while setting up
    /// Command Line Tools / the venv on a fresh install. `nil` once bootstrap is done (or
    /// never started) - the file is written as `<unix_ts>|<stage_id>|<message>` and
    /// overwritten atomically (write-then-rename) so this never reads a half-written line.
    func currentBootstrapStatus() -> BootstrapStatus? {
        Self.readStatusFile(atPath: Self.bootstrapStatusPath)
    }

    /// Same idea as `currentBootstrapStatus()`, but for the STT engine's first load
    /// (model download + first-run compilation) - written by local_server.py right
    /// before it creates the engine for the very first time.
    func currentVoiceBootstrapStatus() -> BootstrapStatus? {
        Self.readStatusFile(atPath: Self.voiceBootstrapStatusPath)
    }

    private static func readStatusFile(atPath path: String) -> BootstrapStatus? {
        guard let data = FileManager.default.contents(atPath: path),
              let line = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !line.isEmpty else { return nil }
        let parts = line.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count == 3 else { return nil }
        return BootstrapStatus(stage: String(parts[1]), message: String(parts[2]))
    }

    /// Checks whether the app bundle or its large bundled resources (the ~2.5GB model
    /// blob, the ollama binary) are iCloud placeholders that macOS hasn't fully
    /// downloaded locally. Reading/mapping such a file mid-eviction is what causes a
    /// hard SIGBUS crash instead of a normal error - this catches it ahead of time.
    /// Returns a user-facing German message if a problem is found, `nil` otherwise.
    func iCloudPlaceholderIssue() -> String? {
        let fileManager = FileManager.default
        let resourceKeys: Set<URLResourceKey> = [.isUbiquitousItemKey, .ubiquitousItemDownloadingStatusKey]

        func isUndownloadedPlaceholder(_ url: URL) -> Bool {
            guard let values = try? url.resourceValues(forKeys: resourceKeys) else { return false }
            return Self.isUndownloadedPlaceholder(
                isUbiquitousItem: values.isUbiquitousItem,
                downloadingStatus: values.ubiquitousItemDownloadingStatus
            )
        }

        var pathsToCheck: [String] = [Bundle.main.bundlePath]
        if let resourcePath = Bundle.main.resourcePath {
            pathsToCheck.append(resourcePath + "/ollama-runtime/ollama")
            pathsToCheck.append(resourcePath + "/JarvisBackend/app/jarvis.py")
            let bundledModelsPath = resourcePath + "/bundled-models"
            if let enumerator = fileManager.enumerator(atPath: bundledModelsPath) {
                for case let relativePath as String in enumerator {
                    let fullPath = bundledModelsPath + "/" + relativePath
                    let size = (try? fileManager.attributesOfItem(atPath: fullPath)[.size] as? Int) ?? nil
                    if let size, size > 10_000_000 {
                        pathsToCheck.append(fullPath)
                    }
                }
            }
        }

        for path in pathsToCheck where isUndownloadedPlaceholder(URL(fileURLWithPath: path)) {
            return "Jarvis liegt in einem iCloud-synchronisierten Ordner (z. B. Desktop) und macOS hat Teile davon ausgelagert, um Speicherplatz zu sparen. Bitte JarvisApp.app nach /Applications verschieben und erneut starten - sonst kann die App abstürzen."
        }
        return nil
    }

    @discardableResult
    func start() -> Bool {
        // Only trust an already-running process if its venv is still intact - otherwise
        // a zombie process left over from a deleted/replaced JARVIS-OS folder (e.g. after
        // extracting a fresh export on top of an old one) silently blocks every future
        // self-heal attempt, since it keeps answering health checks despite its own venv
        // being gone.
        if serverProcess?.isRunning == true && venvPythonExists {
            isRunning = true
            return true
        }

        let quotedBackendSourcePath = Self.shellQuote(backendSourcePath)
        let quotedDataDirectory = Self.shellQuote(dataDirectory)
        let quotedVenvPath = Self.shellQuote(venvPath)
        let process = Process()
        process.currentDirectoryURL = URL(fileURLWithPath: backendSourcePath)
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            """
            LOG_FILE=\(Self.shellQuote(Self.startLogPath))
            exec >"$LOG_FILE" 2>&1
            set -e
            cd \(quotedBackendSourcePath)
            DATA_DIR=\(quotedDataDirectory)
            VENV_DIR=\(quotedVenvPath)
            mkdir -p "$DATA_DIR"
            STATUS_FILE=\(Self.shellQuote(Self.bootstrapStatusPath))
            rm -f "$STATUS_FILE"
            write_status() {
                printf '%s|%s|%s\n' "$(date +%s)" "$1" "$2" > "$STATUS_FILE.tmp"
                mv "$STATUS_FILE.tmp" "$STATUS_FILE"
            }
            # One-time migration for testers upgrading from the old "manual folder at
            # ~/Desktop/JARVIS-OS" setup: copy (never move) their existing memory/cache/
            # config into the new Application Support location, guarded so it only ever
            # runs once. The old folder is left untouched as a safety net.
            OLD_ROOT="$HOME/Desktop/JARVIS-OS"
            if [ -d "$OLD_ROOT/memory" ] && [ ! -d "$DATA_DIR/memory" ]; then
                cp -R "$OLD_ROOT/memory" "$DATA_DIR/memory" 2>/dev/null || true
            fi
            if [ -d "$OLD_ROOT/.cache" ] && [ ! -d "$DATA_DIR/.cache" ]; then
                cp -R "$OLD_ROOT/.cache" "$DATA_DIR/.cache" 2>/dev/null || true
            fi
            if [ -f "$OLD_ROOT/config.json" ] && [ ! -f "$DATA_DIR/config.json" ]; then
                cp "$OLD_ROOT/config.json" "$DATA_DIR/config.json" 2>/dev/null || true
            fi
            health_ok() {
                /usr/bin/curl -fsS --max-time 2 http://127.0.0.1:8765/api/health >/dev/null 2>&1
            }
            # A single successful health check isn't proof of a stable server - it can
            # also be a just-killed previous instance still answering for a few hundred ms
            # before its socket actually releases (SIGTERM isn't synchronous). Confirm the
            # health check keeps succeeding across a short window before trusting it and
            # skipping the real start below - same "verify actual liveness, don't trust a
            # single snapshot" standard the Ollama readiness loops further down already use.
            if [ -x "$VENV_DIR/bin/python3" ] && health_ok; then
                STILL_UP=1
                for _ in 1 2 3; do
                    /bin/sleep 1
                    if ! health_ok; then
                        STILL_UP=0
                        break
                    fi
                done
                if [ "$STILL_UP" -eq 1 ]; then
                    echo "Jarvis local server already running."
                    exit 0
                fi
                echo "Health check succeeded once but stopped responding during confirmation (likely a dying previous instance) - continuing with a fresh start."
            fi

            try_system_ollama() {
                export OLLAMA_HOST="127.0.0.1:11434"
                unset JARVIS_BUNDLED_OLLAMA
                local url="http://127.0.0.1:11434/api/tags"
                if /usr/bin/curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
                    return 0
                fi
                if command -v ollama >/dev/null 2>&1; then
                    nohup ollama serve >/tmp/jarvis_ollama.log 2>&1 &
                elif [ -d "/Applications/Ollama.app" ]; then
                    /usr/bin/open -a Ollama >/tmp/jarvis_ollama.log 2>&1 &
                fi
                for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
                    if /usr/bin/curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
                        return 0
                    fi
                    /bin/sleep 1
                done
                return 1
            }

            BUNDLED_OLLAMA=\(Self.shellQuote((Bundle.main.resourcePath ?? "") + "/ollama-runtime/ollama"))
            if [ -x "$BUNDLED_OLLAMA" ]; then
                export OLLAMA_HOST="127.0.0.1:11500"
                export JARVIS_BUNDLED_OLLAMA="$BUNDLED_OLLAMA"
                export OLLAMA_MODELS="$HOME/Library/Application Support/Jarvis/ollama-models"
                BUNDLED_MODELS_SRC=\(Self.shellQuote((Bundle.main.resourcePath ?? "") + "/bundled-models/phi4-mini"))
                PHI4_MANIFEST="$OLLAMA_MODELS/manifests/registry.ollama.ai/library/phi4-mini/latest"
                if [ -d "$BUNDLED_MODELS_SRC" ] && [ ! -f "$PHI4_MANIFEST" ]; then
                    mkdir -p "$OLLAMA_MODELS"
                    cp -R "$BUNDLED_MODELS_SRC/." "$OLLAMA_MODELS/" 2>/dev/null || true
                fi
                BUNDLED_URL="http://$OLLAMA_HOST/api/tags"
                if ! /usr/bin/curl -fsS --max-time 2 "$BUNDLED_URL" >/dev/null 2>&1; then
                    nohup "$BUNDLED_OLLAMA" serve >/tmp/jarvis_ollama.log 2>&1 &
                    BUNDLED_OK=1
                    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
                        if /usr/bin/curl -fsS --max-time 2 "$BUNDLED_URL" >/dev/null 2>&1; then
                            BUNDLED_OK=0
                            break
                        fi
                        /bin/sleep 1
                    done
                    if [ "$BUNDLED_OK" -ne 0 ]; then
                        echo "Gebuendeltes Ollama nach 15s nicht erreichbar, Fallback auf System-Ollama."
                        try_system_ollama || echo "Kein Ollama verfuegbar (weder gebuendelt noch System) - Jarvis laeuft ohne lokales Modell."
                    fi
                fi
            else
                try_system_ollama || echo "Kein Ollama verfuegbar - Jarvis laeuft ohne lokales Modell."
            fi

            PIDS=$(/usr/sbin/lsof -nP -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)
            if [ -n "$PIDS" ]; then
                echo "Stopping stale Jarvis server on port 8765: $PIDS"
                /bin/kill $PIDS 2>/dev/null || true
                /bin/sleep 0.7
            fi

            NEEDS_BOOTSTRAP=0
            [ ! -x "$VENV_DIR/bin/python3" ] && NEEDS_BOOTSTRAP=1
            if [ "$NEEDS_BOOTSTRAP" -eq 1 ]; then
                write_status "checking_clt" "Pruefe, ob Xcode Command Line Tools installiert sind ..."
                if ! xcode-select -p >/dev/null 2>&1; then
                    write_status "clt_prompt" "Einmalige Einrichtung: Ein Systemfenster ist erschienen (ggf. hinter anderen Fenstern) - bitte dort auf Installieren klicken. Dauert danach ca. 10-15 Minuten."
                    xcode-select --install >/dev/null 2>&1 || true
                    write_status "clt_installing" "Xcode Command Line Tools werden installiert - bitte warten (kann bis zu 15 Minuten dauern)."
                    CLT_OK=1
                    for _ in $(seq 1 180); do
                        if xcode-select -p >/dev/null 2>&1; then
                            CLT_OK=0
                            break
                        fi
                        /bin/sleep 5
                    done
                    if [ "$CLT_OK" -ne 0 ]; then
                        write_status "error" "Xcode Command Line Tools wurden nicht installiert. Bitte im Terminal 'xcode-select --install' ausfuehren und Jarvis danach erneut starten."
                        echo "FEHLER: Xcode Command Line Tools nach 15 Minuten nicht installiert."
                        exit 1
                    fi
                fi
            fi

            if [ ! -x "$VENV_DIR/bin/python3" ]; then
                write_status "creating_venv" "Einmalige Ersteinrichtung: Python-Umgebung wird angelegt ..."
                if ! command -v python3 >/dev/null 2>&1; then
                    write_status "error" "python3 ist auf diesem Mac nicht installiert. Bitte im Terminal 'xcode-select --install' ausfuehren und Jarvis danach erneut starten."
                    echo "FEHLER: python3 ist auf diesem Mac nicht installiert."
                    exit 1
                fi
                python3 -m venv "$VENV_DIR"
            fi
            # This import check is normally fast (~a few seconds), but faster_whisper/torch
            # do real device/backend probing on import, not just a trivial import - under
            # system load (heavy CPU/IO contention from other processes) it can legitimately
            # take much longer without being hung. Run it in the background and poll so we
            # can tell the user it's still working instead of leaving the app silently on
            # "Nicht verbunden" - same write_status mechanism used for the CLT/venv bootstrap
            # above.
            write_status "checking_dependencies" "Python-Umgebung wird geprueft ..."
            "$VENV_DIR/bin/python3" -c "import numpy, sounddevice, dotenv, openai, edge_tts, miniaudio, faster_whisper, torch" >/dev/null 2>&1 &
            DEP_CHECK_PID=$!
            DEP_CHECK_WAITED=0
            DEP_CHECK_WARNED=0
            while kill -0 "$DEP_CHECK_PID" 2>/dev/null; do
                /bin/sleep 2
                DEP_CHECK_WAITED=$((DEP_CHECK_WAITED + 2))
                if [ "$DEP_CHECK_WAITED" -ge 16 ] && [ "$DEP_CHECK_WARNED" -eq 0 ]; then
                    write_status "checking_dependencies" "Python-Umgebung wird vorbereitet - kann bei hoher Systemlast laenger dauern ..."
                    DEP_CHECK_WARNED=1
                fi
            done
            DEP_CHECK_STATUS=0
            wait "$DEP_CHECK_PID" || DEP_CHECK_STATUS=$?
            if [ "$DEP_CHECK_STATUS" -ne 0 ]; then
                write_status "installing_packages" "Einmalige Ersteinrichtung: Python-Pakete werden vorbereitet ..."
                "$VENV_DIR/bin/python3" -m pip install --upgrade pip >/dev/null 2>&1 || true
                TOTAL=$(grep -vc '^[[:space:]]*$' requirements.txt)
                N=0
                while IFS= read -r PKG; do
                    [ -z "$PKG" ] && continue
                    N=$((N + 1))
                    write_status "installing_packages" "Einmalige Ersteinrichtung: Installiere Paket $N von $TOTAL ($PKG) - kann insgesamt 10-15 Minuten dauern. Mac bitte nicht in den Ruhezustand versetzen."
                    "$VENV_DIR/bin/python3" -m pip install "$PKG"
                done < requirements.txt
            fi
            write_status "starting_server" "Python-Umgebung bereit, Jarvis-Kern startet ..."
            export JARVIS_DATA_DIR="$DATA_DIR"
            exec "$VENV_DIR/bin/python3" app/jarvis.py --local-server
            """
        ]
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        do {
            try process.run()
            serverProcess = process
            isRunning = true
            lastLaunchError = nil
            return true
        } catch {
            lastLaunchError = error.localizedDescription
            isRunning = false
            return false
        }
    }

    func stop() async {
        await stopSpeaking()
        if let process = serverProcess, process.isRunning {
            process.terminate()
        }
        serverProcess = nil
        isRunning = false
    }

    func stopServerProcessOnly() {
        if let process = serverProcess, process.isRunning {
            process.terminate()
        }
        serverProcess = nil
        lastLaunchError = nil
        isRunning = false
    }

    /// Synchronous cleanup for a real app quit (`applicationShouldTerminate`), not for
    /// backgrounding.
    func shutdownForAppQuit() {
        if let process = serverProcess, process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
        serverProcess = nil
        isRunning = false

        killBundledOllama()
    }

    /// Kills whatever process is listening on the bundled Ollama's port, independent of
    /// whether *this* app instance started it this session - covers both the shell start
    /// script's `nohup ... &` and the separate self-heal spawn in `model_manager.py`,
    /// since both inherit `OLLAMA_HOST=127.0.0.1:11500` and end up listening on the same
    /// port. Scoped by port rather than process name so an unrelated, independently
    /// running system Ollama (default port 11434) is never touched.
    private func killBundledOllama() {
        let pids = Self.listeningPIDs(onPort: Self.bundledOllamaPort)
        guard !pids.isEmpty else { return }
        for pid in pids { kill(pid, SIGTERM) }

        let deadline = Date().addingTimeInterval(2.0)
        while Date() < deadline {
            if Self.listeningPIDs(onPort: Self.bundledOllamaPort).isEmpty { return }
            Thread.sleep(forTimeInterval: 0.1)
        }
        for pid in Self.listeningPIDs(onPort: Self.bundledOllamaPort) { kill(pid, SIGKILL) }
    }

    private static func listeningPIDs(onPort port: Int) -> [pid_t] {
        let lookup = Process()
        lookup.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lookup.arguments = ["-nP", "-tiTCP:\(port)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        lookup.standardOutput = pipe
        lookup.standardError = Pipe()
        do {
            try lookup.run()
        } catch {
            return []
        }
        lookup.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8) else { return [] }
        return output.split(separator: "\n").compactMap { pid_t($0.trimmingCharacters(in: .whitespaces)) }
    }

    /// Surfaces a script-level start failure (e.g. missing `.venv`) from the log file to the UI.
    func captureLaunchFailureDetail() {
        guard lastLaunchError == nil else { return }
        guard let data = FileManager.default.contents(atPath: Self.startLogPath),
              let text = String(data: data, encoding: .utf8) else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        lastLaunchError = String(trimmed.suffix(600))
    }


    func speakText(
        _ text: String,
        onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)? = nil
    ) async throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        await stopSpeaking()

        let inputData = try JSONSerialization.data(withJSONObject: ["text": trimmed], options: [])
        let process = Process()
        let stdinPipe = Pipe()
        let stderrPipe = Pipe()
        process.currentDirectoryURL = URL(fileURLWithPath: backendSourcePath)
        process.environment = pythonEnvironment()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            "cd \(Self.shellQuote(backendSourcePath)) && \(Self.shellQuote(venvPath))/bin/python3 app/tts_bridge.py"
        ]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        process.standardError = stderrPipe

        ttsProcess = process
        try process.run()
        stdinPipe.fileHandleForWriting.write(inputData)
        try? stdinPipe.fileHandleForWriting.close()

        let stderrReader = Task.detached {
            let handle = stderrPipe.fileHandleForReading
            var buffer = Data()
            while true {
                let data = handle.availableData
                if data.isEmpty { break }
                buffer.append(data)
                while let newline = buffer.firstIndex(of: 10) {
                    let lineData = buffer[..<newline]
                    buffer.removeSubrange(...newline)
                    guard let line = String(data: lineData, encoding: .utf8) else { continue }
                    if let event = BridgeRuntimeEvent(line: line) {
                        await MainActor.run { onEvent?(event) }
                    }
                }
            }
            if !buffer.isEmpty, let line = String(data: buffer, encoding: .utf8),
               let event = BridgeRuntimeEvent(line: line) {
                await MainActor.run { onEvent?(event) }
            }
        }

        let status: Int32 = await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                process.waitUntilExit()
                continuation.resume(returning: process.terminationStatus)
            }
        }
        _ = await stderrReader.result

        if ttsProcess === process {
            ttsProcess = nil
        }

        if status != 0 && status != 15 && status != 130 {
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errorText = String(data: errorData, encoding: .utf8) ?? ""
            throw BridgeError.processFailed(errorText.isEmpty ? "Edge-TTS konnte nicht abgespielt werden." : errorText)
        }
    }

    func stopSpeaking() async {
        await terminateProcess(at: \.ttsProcess)
        try? await Task.sleep(for: .milliseconds(250))
    }

    /// Cancels an in-flight prefetch synthesis without touching current playback -
    /// used when the streaming answer/queue is abandoned (e.g. user stops or sends a
    /// new message) before a prefetched segment was ever played.
    func cancelPendingSynthesis() async {
        await terminateProcess(at: \.synthesizeProcess)
    }

    private func terminateProcess(at keyPath: ReferenceWritableKeyPath<LocalServerController, Process?>) async {
        guard let process = self[keyPath: keyPath] else { return }
        self[keyPath: keyPath] = nil
        if process.isRunning {
            process.terminate()
            await withTaskGroup(of: Void.self) { group in
                group.addTask {
                    await withCheckedContinuation { continuation in
                        DispatchQueue.global(qos: .userInitiated).async {
                            process.waitUntilExit()
                            continuation.resume()
                        }
                    }
                }
                group.addTask {
                    try? await Task.sleep(for: .seconds(1))
                }
                await group.next()
                group.cancelAll()
            }
        }
    }

    /// Synthesizes `text` to an audio file WITHOUT playing it - lets a caller prefetch
    /// the next segment's audio while a previous one is still playing via `playSpeechFile`.
    /// Throws (e.g. if `tts_provider` isn't "edge") so callers can fall back to
    /// `speakText` for that segment instead of silently losing audio.
    func synthesizeSpeech(
        _ text: String,
        onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)? = nil
    ) async throws -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw BridgeError.processFailed("Kein Text zum Synthetisieren.")
        }

        let inputData = try JSONSerialization.data(withJSONObject: ["text": trimmed], options: [])
        let (stdoutData, status, stderrPipe) = try await runTTSBridgeSubprocess(
            arguments: ["--synthesize"],
            stdinData: inputData,
            trackAt: \.synthesizeProcess,
            onEvent: onEvent
        )

        guard status == 0 else {
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errorText = String(data: errorData, encoding: .utf8) ?? ""
            throw BridgeError.processFailed(errorText.isEmpty ? "Sprachsynthese fehlgeschlagen." : errorText)
        }

        struct SynthesizeResponse: Decodable { let ok: Bool; let audio_file: String? }
        guard let response = try? JSONDecoder().decode(SynthesizeResponse.self, from: stdoutData),
              response.ok, let audioFile = response.audio_file else {
            throw BridgeError.invalidJSON(String(data: stdoutData, encoding: .utf8) ?? "")
        }
        return audioFile
    }

    /// Plays a file previously produced by `synthesizeSpeech`. Shares `ttsProcess`
    /// tracking with `speakText`, so `stopSpeaking()` interrupts this the same way.
    func playSpeechFile(
        _ path: String,
        onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)? = nil
    ) async throws {
        await stopSpeaking()

        let inputData = try JSONSerialization.data(withJSONObject: ["audio_file": path], options: [])
        let (_, status, stderrPipe) = try await runTTSBridgeSubprocess(
            arguments: ["--play"],
            stdinData: inputData,
            trackAt: \.ttsProcess,
            onEvent: onEvent
        )

        if status != 0 && status != 15 && status != 130 {
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errorText = String(data: errorData, encoding: .utf8) ?? ""
            throw BridgeError.processFailed(errorText.isEmpty ? "Audiodatei konnte nicht abgespielt werden." : errorText)
        }
    }

    /// Shared subprocess plumbing behind `speakText`/`synthesizeSpeech`/`playSpeechFile`:
    /// runs `app/tts_bridge.py` with the given arguments, feeds `stdinData` on stdin,
    /// forwards stderr lines to `onEvent`, and returns stdout + exit status once done.
    private func runTTSBridgeSubprocess(
        arguments: [String],
        stdinData: Data,
        trackAt keyPath: ReferenceWritableKeyPath<LocalServerController, Process?>,
        onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?
    ) async throws -> (stdout: Data, status: Int32, stderrPipe: Pipe) {
        let process = Process()
        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.currentDirectoryURL = URL(fileURLWithPath: backendSourcePath)
        process.environment = pythonEnvironment()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        let argsSuffix = arguments.map { " \(Self.shellQuote($0))" }.joined()
        process.arguments = [
            "-lc",
            "cd \(Self.shellQuote(backendSourcePath)) && \(Self.shellQuote(venvPath))/bin/python3 app/tts_bridge.py\(argsSuffix)"
        ]
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        self[keyPath: keyPath] = process
        try process.run()
        stdinPipe.fileHandleForWriting.write(stdinData)
        try? stdinPipe.fileHandleForWriting.close()

        let stderrReader = Task.detached {
            let handle = stderrPipe.fileHandleForReading
            var buffer = Data()
            while true {
                let data = handle.availableData
                if data.isEmpty { break }
                buffer.append(data)
                while let newline = buffer.firstIndex(of: 10) {
                    let lineData = buffer[..<newline]
                    buffer.removeSubrange(...newline)
                    guard let line = String(data: lineData, encoding: .utf8) else { continue }
                    if let event = BridgeRuntimeEvent(line: line) {
                        await MainActor.run { onEvent?(event) }
                    }
                }
            }
            if !buffer.isEmpty, let line = String(data: buffer, encoding: .utf8),
               let event = BridgeRuntimeEvent(line: line) {
                await MainActor.run { onEvent?(event) }
            }
        }

        // Must read stdout and wait for exit off the main thread: readDataToEndOfFile()
        // is a synchronous, blocking call with no async variant - calling it directly here
        // would block this @MainActor-isolated function's caller (i.e. the real main
        // thread) for the process's whole lifetime, freezing the entire app UI. Confirmed
        // as the root cause of a full UI freeze during every TTS synth/playback call - see
        // commit message.
        let (stdoutData, status): (Data, Int32) = await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let data = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                continuation.resume(returning: (data, process.terminationStatus))
            }
        }
        _ = await stderrReader.result

        if self[keyPath: keyPath] === process {
            self[keyPath: keyPath] = nil
        }

        return (stdoutData, status, stderrPipe)
    }

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

        // Same fix as runTTSBridgeSubprocess: read stdout and wait for exit off the main
        // thread, not directly here - this call runs up to ~14s (the live-transcription
        // window), and a blocking readDataToEndOfFile() on the main thread for that long
        // was confirmed to freeze the entire app UI (no clicks, no redraws) for the whole
        // duration.
        let (stdoutData, status): (Data, Int32) = await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let data = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                continuation.resume(returning: (data, process.terminationStatus))
            }
        }
        let stderrText = await stderrReader.value

        guard status == 0 else {
            throw BridgeError.processFailed(stderrText.isEmpty ? "Live-Transkription fehlgeschlagen." : stderrText)
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
            throw BridgeError.processFailed("Apple-Speech-Helper fehlt: \(sourceFile)")
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
            throw BridgeError.processFailed("Apple-Speech-Helper Kompilierung hat zu lange gedauert.")
        }

        guard process.terminationStatus == 0 else {
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let errorText = String(data: errorData, encoding: .utf8) ?? ""
            throw BridgeError.processFailed(errorText.isEmpty ? "Apple-Speech-Helper konnte nicht kompiliert werden." : "Apple-Speech-Helper konnte nicht kompiliert werden: \(errorText)")
        }
    }

    func warmVoicePipeline() {
        if warmupProcess?.isRunning == true {
            return
        }

        let process = Process()
        let stdinPipe = Pipe()
        process.currentDirectoryURL = URL(fileURLWithPath: backendSourcePath)
        process.environment = pythonEnvironment()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            "cd \(Self.shellQuote(backendSourcePath)) && \(Self.shellQuote(venvPath))/bin/python3 app/tts_bridge.py"
        ]
        process.standardInput = stdinPipe
        process.standardOutput = Pipe()
        process.standardError = Pipe()

        do {
            try process.run()
            warmupProcess = process
        } catch {
            return
        }

        Task.detached {
            let payload = try? JSONSerialization.data(withJSONObject: ["text": ""], options: [])
            if let payload {
                stdinPipe.fileHandleForWriting.write(payload)
            }
            try? stdinPipe.fileHandleForWriting.close()
            process.waitUntilExit()
            await MainActor.run {
                if self.warmupProcess === process {
                    self.warmupProcess = nil
                }
            }
        }
    }

    func health() async throws -> ServerHealth {
        let data = try await apiClient.health()
        isRunning = true
        return data
    }

    func chat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        do {
            let answer = try await apiClient.sendChat(message, history: history)
            isRunning = true
            return answer
        } catch {
            let response: ChatResponse = try await bridge(
                command: "chat",
                payload: ["message": message, "history": history]
            )
            isRunning = true
            return response
        }
    }

    func chatStream(
        _ message: String,
        history: [[String: String]] = [],
        onChunk: @MainActor @escaping (String) -> Void
    ) async throws -> String {
        do {
            let answer = try await apiClient.sendChatStream(message, history: history, onChunk: onChunk)
            isRunning = true
            return answer
        } catch {
            let response: ChatResponse = try await bridge(
                command: "chat",
                payload: ["message": message, "history": history]
            )
            isRunning = true
            onChunk(response.answer)
            return response.answer
        }
    }

    func listenAndRespond(history: [[String: String]] = []) async throws -> ListenResponse {
        let response = try await apiClient.listenAndRespond(history: history)
        isRunning = true
        return response
    }

    func listenAndRespond(
        history: [[String: String]] = [],
        onEvent: @MainActor @escaping (BridgeRuntimeEvent) -> Void
    ) async throws -> ListenResponse {
        let response: ListenResponse = try await bridge(
            command: "listen",
            payload: ["history": history],
            onEvent: onEvent
        )
        isRunning = true
        return response
    }

    func transcribeVoice(audioPath: String, sampleRate: Double) async throws -> VoiceTranscriptionResponse {
        try await apiClient.transcribeVoice(audioPath: audioPath, sampleRate: sampleRate)
    }

    func prewarmVoicePipeline() async {
        do {
            _ = try await apiClient.prewarmVoicePipeline()
            isRunning = true
        } catch {
            // Keep the fallback lightweight; avoid a second competing audio process.
            isRunning = true
        }
    }

    func cancelListening() async {
        do {
            try await apiClient.cancelListening()
            isRunning = true
        } catch {
            isRunning = true
        }
    }

    func setVoiceSpeakingState(_ isSpeaking: Bool) async {
        do {
            try await apiClient.setVoiceSpeakingState(isSpeaking)
            isRunning = true
        } catch {
            isRunning = true
        }
    }

    func models() async throws -> ModelStatus {
        let status = try await apiClient.models()
        isRunning = true
        return status
    }

    func pullModel(_ model: String) async throws -> ScanProgress {
        let progress = try await apiClient.pullModel(model)
        isRunning = true
        return progress
    }

    func scanStatus() async throws -> ScanStatusBundle {
        let status = try await apiClient.scanStatus()
        isRunning = true
        return status
    }

    func startMailFolderScan() async throws -> ScanProgress {
        let progress = try await apiClient.startMailFolderScan()
        isRunning = true
        return progress
    }

    func startMailBackgroundScan() async throws -> ScanProgress {
        let progress = try await apiClient.startMailBackgroundScan()
        isRunning = true
        return progress
    }

    func startPhotoIndexScan() async throws -> ScanProgress {
        let progress = try await apiClient.startPhotoIndexScan()
        isRunning = true
        return progress
    }

    func startLocalPhotoVisionAnalysis() async throws -> ScanProgress {
        let progress = try await apiClient.startLocalPhotoVisionAnalysis()
        isRunning = true
        return progress
    }

    func resetLocalPhotoVisionDescriptions() async throws -> ScanProgress {
        let progress = try await apiClient.resetLocalPhotoVisionDescriptions()
        isRunning = true
        return progress
    }

    func localPhotoVisionStatus() async throws -> LocalVisionStatus {
        try await apiClient.localPhotoVisionStatus()
    }

    func calendarOverview() async throws -> CalendarOverviewPayload {
        try await apiClient.calendarOverview()
    }

    func mailOverview() async throws -> MailOverviewPayload {
        try await apiClient.mailOverview()
    }

    func musicOverview() async throws -> MusicOverviewPayload {
        try await apiClient.musicOverview()
    }

    func dailyBriefing() async throws -> DailyBriefingPayload {
        try await apiClient.dailyBriefing()
    }

    func conversationHistory() async throws -> ConversationHistoryPayload {
        try await apiClient.conversationHistory()
    }

    func startFileIndexScan() async throws -> ScanProgress {
        let progress = try await apiClient.startFileIndexScan()
        isRunning = true
        return progress
    }

    func searchFiles(query: String) async throws -> FileSearchPayload {
        do {
            let payload = try await apiClient.searchFiles(query: query)
            isRunning = true
            return payload
        } catch {
            let payload: FileSearchPayload = try await bridge(
                command: "files_search",
                payload: ["query": query]
            )
            isRunning = true
            return payload
        }
    }

    func moveFileSearchResults(query: String, targetFolder: String) async throws -> String {
        do {
            let message = try await apiClient.moveFileSearchResults(query: query, targetFolder: targetFolder)
            isRunning = true
            return message
        } catch {
            struct Response: Decodable { let message: String }
            let response: Response = try await bridge(
                command: "files_move_search_results",
                payload: ["query": query, "target_folder": targetFolder]
            )
            isRunning = true
            return response.message
        }
    }

    func resetFileIndex() async throws -> ScanProgress {
        let progress = try await apiClient.resetFileIndex()
        isRunning = true
        return progress
    }

    func photoPermissionStatus() async throws -> String {
        try await apiClient.photoPermissionStatus()
    }

    func requestPhotoPermission() async throws -> String {
        try await apiClient.requestPhotoPermission()
    }

    func resetPhotoIndex() async throws -> ScanProgress {
        let progress = try await apiClient.resetPhotoIndex()
        isRunning = true
        return progress
    }

    func setModel(provider: String? = nil, model: String? = nil) async throws -> ModelStatus {
        let status = try await apiClient.setModel(provider: provider, model: model)
        isRunning = true
        return status
    }

    func setFastVoiceMode(_ enabled: Bool) async throws {
        try await apiClient.setFastVoiceMode(enabled)
        isRunning = true
    }

    func setStoreConversation(_ enabled: Bool) async throws {
        try await apiClient.setStoreConversation(enabled)
        isRunning = true
    }

    func privacyStatus() async throws -> String {
        try await apiClient.privacyStatus()
    }

    func permissions() async throws -> [String: PermissionInfo] {
        try await apiClient.permissions()
    }

    func setPermission(_ permission: String, allowed: Bool) async throws -> [String: PermissionInfo] {
        try await apiClient.setPermission(permission, allowed: allowed)
    }

    func exportPrivacyData() async throws -> String {
        try await apiClient.exportPrivacyData()
    }

    func deleteHistory() async throws -> String {
        try await apiClient.deleteHistory()
    }

    func clearLogs() async throws -> String {
        try await apiClient.clearLogs()
    }

    func memoryFacts(search: String = "", category: String = "") async throws -> MemoryFactsResponse {
        try await apiClient.memoryFacts(search: search, category: category)
    }

    @discardableResult
    func updateMemoryFact(id: String, fields: [String: String]) async throws -> Bool {
        try await apiClient.updateMemoryFact(id: id, fields: fields)
    }

    @discardableResult
    func confirmMemoryFact(id: String) async throws -> Bool {
        try await apiClient.confirmMemoryFact(id: id)
    }

    @discardableResult
    func rejectMemoryFact(id: String) async throws -> Bool {
        try await apiClient.rejectMemoryFact(id: id)
    }

    @discardableResult
    func deleteMemoryFact(id: String) async throws -> Bool {
        try await apiClient.deleteMemoryFact(id: id)
    }

    func setOpenAIKey(_ apiKey: String) async throws {
        try await apiClient.setOpenAIKey(apiKey)
    }

    func deleteOpenAIKey() async throws {
        try await apiClient.deleteOpenAIKey()
    }

    func setUserProfile(userName: String, salutation: String) async throws {
        let _: EmptyResponse = try await bridge(
            command: "set_user_profile",
            payload: ["user_name": userName, "salutation": salutation]
        )
    }

    private func bridge<T: Decodable>(
        command: String,
        payload: [String: Any] = [:],
        onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)? = nil
    ) async throws -> T {
        try await Task.detached(priority: .userInitiated) { [backendSourcePath, venvPath, dataDirectory] in
            var request = payload
            request["command"] = command
            let inputData = try JSONSerialization.data(withJSONObject: request, options: [])

            let process = Process()
            let stdinPipe = Pipe()
            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.currentDirectoryURL = URL(fileURLWithPath: backendSourcePath)
            var env = ProcessInfo.processInfo.environment
            env["JARVIS_DATA_DIR"] = dataDirectory
            process.environment = env
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [
                "-lc",
                "cd \(Self.shellQuote(backendSourcePath)) && \(Self.shellQuote(venvPath))/bin/python3 app/app_bridge.py"
            ]
            process.standardInput = stdinPipe
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe

            try process.run()
            let stderrReader = Task.detached {
                let handle = stderrPipe.fileHandleForReading
                var buffer = Data()
                while true {
                    let data = handle.availableData
                    if data.isEmpty { break }
                    buffer.append(data)
                    while let newline = buffer.firstIndex(of: 10) {
                        let lineData = buffer[..<newline]
                        buffer.removeSubrange(...newline)
                        guard let line = String(data: lineData, encoding: .utf8) else { continue }
                        if let event = BridgeRuntimeEvent(line: line) {
                            await MainActor.run { onEvent?(event) }
                        }
                    }
                }
                if !buffer.isEmpty, let line = String(data: buffer, encoding: .utf8),
                   let event = BridgeRuntimeEvent(line: line) {
                    await MainActor.run { onEvent?(event) }
                }
            }
            stdinPipe.fileHandleForWriting.write(inputData)
            try? stdinPipe.fileHandleForWriting.close()
            process.waitUntilExit()
            _ = await stderrReader.result

            let outputData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            if process.terminationStatus != 0 {
                let errorText = String(data: errorData, encoding: .utf8) ?? ""
                throw BridgeError.processFailed(errorText)
            }

            let envelope: BridgeEnvelope<T> = try decodeBridgeEnvelope(from: outputData)
            if envelope.ok, let data = envelope.data {
                return data
            }
            let errorText = [envelope.error, envelope.detail]
                .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: ": ")
            throw BridgeError.commandFailed(errorText.isEmpty ? "unknown_error" : errorText)
        }.value
    }
}

private extension LocalServerController {
    /// Where `app/` (the read-only Python source) lives. The bundled copy inside the
    /// signed `.app` wins whenever present (covers both a real `/Applications` install
    /// and an Xcode debug run, since both go through the same Resources build phase) -
    /// the walk-up candidates below only matter for `swift run`/`swift build` via the
    /// legacy SPM entry point, and `~/Desktop/JARVIS-OS` is kept purely as a transitional
    /// fallback for testers who haven't yet received a build with the bundled backend.
    nonisolated static func detectBackendSourcePath() -> String {
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

    /// Writable location for the venv, memory, cache, config, and compiled helper
    /// binaries - `~/Library/Application Support/<bundle id>`. Deliberately a different,
    /// sibling folder from the existing `~/Library/Application Support/Jarvis/ollama-models`
    /// (used for the bundled phi4-mini model) rather than unifying the two - that
    /// existing path is already working and untouched by this change.
    nonisolated static func detectDataDirectory() -> String {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let identifier = Bundle.main.bundleIdentifier ?? "com.leon.jarvis"
        return base.appendingPathComponent(identifier).path
    }

    nonisolated static func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    /// Pure decision logic behind `iCloudPlaceholderIssue()`, split out so it can be
    /// exercised with synthetic inputs (real iCloud eviction isn't reliably triggerable
    /// from a script - see verification notes) instead of only against live resourceValues.
    nonisolated static func isUndownloadedPlaceholder(
        isUbiquitousItem: Bool?,
        downloadingStatus: URLUbiquitousItemDownloadingStatus?
    ) -> Bool {
        guard isUbiquitousItem == true else { return false }
        return downloadingStatus != .current
    }
}

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

private func decodeBridgeEnvelope<T: Decodable>(from outputData: Data) throws -> BridgeEnvelope<T> {
    let decoder = JSONDecoder()
    if let envelope = try? decoder.decode(BridgeEnvelope<T>.self, from: outputData) {
        return envelope
    }

    let output = String(data: outputData, encoding: .utf8) ?? ""
    let lines = output
        .split(whereSeparator: \.isNewline)
        .map(String.init)
        .reversed()
    for line in lines {
        guard line.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("{") else { continue }
        if let data = line.data(using: .utf8),
           let envelope = try? decoder.decode(BridgeEnvelope<T>.self, from: data) {
            return envelope
        }
    }

    throw BridgeError.invalidJSON(output)
}

private struct BridgeEnvelope<T: Decodable>: Decodable {
    let ok: Bool
    let data: T?
    let error: String?
    let detail: String?
}

private struct EmptyResponse: Decodable {}

private struct BridgeStreamChunk: Decodable {
    let chunk: String
}

private struct BridgeTranscriptPayload: Decodable {
    let text: String
}

private enum BridgeError: LocalizedError {
    case processFailed(String)
    case commandFailed(String)
    case invalidJSON(String)

    var errorDescription: String? {
        switch self {
        case .processFailed(let text): return text.isEmpty ? "Python-Bridge konnte nicht gestartet werden." : text
        case .commandFailed(let text): return text
        case .invalidJSON(let text):
            let preview = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return preview.isEmpty ? "Python-Bridge hat keine Antwort geliefert." : "Python-Bridge lieferte kein gültiges JSON: \(preview.prefix(300))"
        }
    }
}
