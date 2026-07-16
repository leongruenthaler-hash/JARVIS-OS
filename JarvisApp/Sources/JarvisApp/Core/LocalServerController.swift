import Foundation

@MainActor
final class LocalServerController: ObservableObject {
    @Published var isRunning = false
    @Published var lastLaunchError: String?

    private static let startLogPath = "/tmp/jarvis_app_server_start.log"
    private static let bundledOllamaPort = 11500
    private static let bootstrapStatusPath = "/tmp/jarvis_app_bootstrap_status.txt"
    private static let voiceBootstrapStatusPath = "/tmp/jarvis_app_voice_bootstrap_status.txt"

    private let projectPath = LocalServerController.detectProjectPath()
    private let apiClient = JarvisAPIClient()
    private var serverProcess: Process?
    private var ttsProcess: Process?
    private var warmupProcess: Process?

    var hasOwnedProcess: Bool { serverProcess != nil }

    /// Whether the Python backend's venv has already been set up. `false` on a fresh
    /// install where `start()` will need to bootstrap it first (slow: several minutes).
    var venvPythonExists: Bool {
        FileManager.default.fileExists(atPath: projectPath + "/.venv/bin/python3")
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
    func start(projectPath: String? = nil) -> Bool {
        // Only trust an already-running process if its venv is still intact - otherwise
        // a zombie process left over from a deleted/replaced JARVIS-OS folder (e.g. after
        // extracting a fresh export on top of an old one) silently blocks every future
        // self-heal attempt, since it keeps answering health checks despite its own venv
        // being gone.
        if serverProcess?.isRunning == true && venvPythonExists {
            isRunning = true
            return true
        }

        let resolvedProjectPath = projectPath ?? self.projectPath
        let quotedProjectPath = Self.shellQuote(resolvedProjectPath)
        let process = Process()
        process.currentDirectoryURL = URL(fileURLWithPath: resolvedProjectPath)
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            """
            LOG_FILE=\(Self.shellQuote(Self.startLogPath))
            exec >"$LOG_FILE" 2>&1
            set -e
            cd \(quotedProjectPath)
            STATUS_FILE=\(Self.shellQuote(Self.bootstrapStatusPath))
            rm -f "$STATUS_FILE"
            write_status() {
                printf '%s|%s|%s\n' "$(date +%s)" "$1" "$2" > "$STATUS_FILE.tmp"
                mv "$STATUS_FILE.tmp" "$STATUS_FILE"
            }
            if [ -x .venv/bin/python3 ] && /usr/bin/curl -fsS --max-time 2 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
                echo "Jarvis local server already running."
                exit 0
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
            [ ! -x .venv/bin/python3 ] && NEEDS_BOOTSTRAP=1
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

            if [ ! -x .venv/bin/python3 ]; then
                write_status "creating_venv" "Einmalige Ersteinrichtung: Python-Umgebung wird angelegt ..."
                if ! command -v python3 >/dev/null 2>&1; then
                    write_status "error" "python3 ist auf diesem Mac nicht installiert. Bitte im Terminal 'xcode-select --install' ausfuehren und Jarvis danach erneut starten."
                    echo "FEHLER: python3 ist auf diesem Mac nicht installiert."
                    exit 1
                fi
                python3 -m venv .venv
            fi
            if ! .venv/bin/python3 -c "import numpy, sounddevice, dotenv, openai, edge_tts, miniaudio, faster_whisper, torch" >/dev/null 2>&1; then
                write_status "installing_packages" "Einmalige Ersteinrichtung: Python-Pakete werden vorbereitet ..."
                .venv/bin/python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
                TOTAL=$(grep -vc '^[[:space:]]*$' requirements.txt)
                N=0
                while IFS= read -r PKG; do
                    [ -z "$PKG" ] && continue
                    N=$((N + 1))
                    write_status "installing_packages" "Einmalige Ersteinrichtung: Installiere Paket $N von $TOTAL ($PKG) - kann insgesamt 10-15 Minuten dauern. Mac bitte nicht in den Ruhezustand versetzen."
                    .venv/bin/python3 -m pip install "$PKG"
                done < requirements.txt
            fi
            write_status "starting_server" "Python-Umgebung bereit, Jarvis-Kern startet ..."
            exec \(quotedProjectPath)/.venv/bin/python3 app/jarvis.py --local-server
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
        process.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            "cd \(Self.shellQuote(projectPath)) && \(Self.shellQuote(projectPath))/.venv/bin/python3 app/tts_bridge.py"
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
        guard let process = ttsProcess else { return }
        ttsProcess = nil
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
        try? await Task.sleep(for: .milliseconds(250))
    }

    func warmVoicePipeline() {
        if warmupProcess?.isRunning == true {
            return
        }

        let process = Process()
        let stdinPipe = Pipe()
        process.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [
            "-lc",
            "cd \(Self.shellQuote(projectPath)) && \(Self.shellQuote(projectPath))/.venv/bin/python3 app/tts_bridge.py"
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
        try await Task.detached(priority: .userInitiated) { [projectPath] in
            var request = payload
            request["command"] = command
            let inputData = try JSONSerialization.data(withJSONObject: request, options: [])

            let process = Process()
            let stdinPipe = Pipe()
            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.currentDirectoryURL = URL(fileURLWithPath: projectPath)
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [
                "-lc",
                "cd \(Self.shellQuote(projectPath)) && \(Self.shellQuote(projectPath))/.venv/bin/python3 app/app_bridge.py"
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
    nonisolated static func detectProjectPath() -> String {
        let fileManager = FileManager.default
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
