import AppKit
import AVFoundation
import Foundation
import SwiftUI
import UserNotifications

@MainActor
final class AppState: ObservableObject {
    @Published var selectedSection: JarvisSection = .home
    @Published var status: JarvisRuntimeStatus = .offline
    @Published var voiceState: JarvisVoiceState = .idle
    /// Growing transcript text while `voiceState == .liveTranscribing` - fed by
    /// `LocalServerController.startLiveTranscription(onPartial:)`. Not yet wired into any
    /// capture flow (Etappe 3); exists now so ChatView's UI binding can be built/tested
    /// independently of that wiring.
    @Published var liveTranscriptText: String = ""
    @Published var messages: [ChatMessage] = [
        ChatMessage(role: .system, text: "Jarvis App bereit. Ich starte den lokalen Core automatisch. Sehr höflich von mir, finde ich.")
    ]
    @Published var privacySummary = "Datenschutzstatus wird geladen ..."
    @Published var permissions: [String: PermissionInfo] = [:]
    @Published var memoryFacts: [MemoryFact] = []
    @Published var memoryFactsTotal = 0
    @Published var automations: [AutomationJob] = []
    @Published var automationsLoading = false
    // Rein lokaler Zustand (kein Server-Roundtrip mehr, siehe setVoiceMode) -
    // wird als Stilanweisung in jede Chat-Anfrage an OpenClaw eingefuegt statt
    // an einen /api/settings/voice-mode-Endpunkt geschickt, den es bei
    // OpenClaw nicht gibt (Rest-Migrations-Plan, Abschnitt 2).
    @Published var voiceMode = UserDefaults.standard.string(forKey: "JarvisVoiceMode") ?? "standard"
    @Published var availableVoiceModes: [String] = ["kurz", "standard", "fokus", "diskret", "privat"]
    // TARS-Style Regler (0-100) - werden per Chat-Anweisung in Jarvis' eigene
    // SOUL.md geschrieben (savePersonalitySettingsToCore), nicht mehr an einen
    // alten Backend-Endpunkt (siehe app/core/personality_manager.py, jetzt
    // ungenutzt). Lokal nur als letzter bekannter Anzeigewert gecacht.
    @Published var humorLevel = UserDefaults.standard.object(forKey: "JarvisHumorLevel") as? Int ?? 60
    @Published var honestyLevel = UserDefaults.standard.object(forKey: "JarvisHonestyLevel") as? Int ?? 90
    @Published var memoryIsLoading = false
    @Published var recentActivity: [ActivityEvent] = []
    @Published var mailResult = "Noch keine Mail-Aktion ausgeführt."
    @Published var mailIsLoading = false
    @Published var mailScanProgress = ScanProgress()
    @Published var mailBackgroundProgress = ScanProgress()
    @Published var photoScanProgress = ScanProgress()
    @Published var photoVisionProgress = ScanProgress()
    @Published var localVisionStatus = LocalVisionStatus(available: false, model: "", installedModels: [], message: "Noch nicht geprüft.")
    @Published var fileScanProgress = ScanProgress()
    @Published var fileResult = "Noch keine Datei-Aktion ausgeführt."
    @Published var fileIsLoading = false
    @Published var fileSearchText = "Rechnungen"
    @Published var fileSearchResults: [FileSearchResult] = []
    @Published var lastFileSearchQuery = ""
    @Published var photoResult = "Noch keine Foto-Aktion ausgeführt."
    @Published var photoPermissionStatus = "unbekannt"
    @Published var photoIsLoading = false
    @Published var calendarOverview = CalendarOverviewPayload(
        calendar: CalendarOverviewSection(items: [], count: 0, message: "Noch nicht geladen.", error: ""),
        reminders: CalendarOverviewSection(items: [], count: 0, message: "Noch nicht geladen.", error: "")
    )
    @Published var mailOverview = MailOverviewPayload(unreadCount: 0, messages: [], message: "Noch nicht geladen.", error: "")
    /// Einzelne Mail-Zusammenfassungen von der "mail-summary-watch"-Automation
    /// (2026-09-12) - ersetzt den alten, gebuendelten MailBackgroundWorker-Text.
    @Published var mailSummaries: [MailSummary] = []
    @Published var musicOverview = MusicOverviewPayload(track: nil, message: "Noch nicht geladen.", error: "")
    @Published var dailyBriefingText = "Noch kein Tagesbriefing geladen."
    @Published var lastAnswerSource = "lokal"
    @Published var composerDraft = ""
    @Published var onboardingCompleted = UserDefaults.standard.bool(forKey: "JarvisOnboardingCompleted")
    @Published var language = UserDefaults.standard.string(forKey: "JarvisLanguage") ?? "Deutsch"
    @Published var userName = UserDefaults.standard.string(forKey: "JarvisUserName") ?? ""
    @Published var userSalutation = UserDefaults.standard.string(forKey: "JarvisUserSalutation") ?? "none"
    @Published var weatherCityName = UserDefaults.standard.string(forKey: "JarvisWeatherCityName") ?? ""
    @Published var weatherCityError: String?
    @Published private(set) var weatherLocation: GeocodedLocation? = {
        guard let data = UserDefaults.standard.data(forKey: "JarvisWeatherLocation") else { return nil }
        return try? JSONDecoder().decode(GeocodedLocation.self, from: data)
    }()
    @Published private(set) var todayActiveUsageMinutes: Double = ProductivityTracker.todayActiveMinutes()
    /// `nil` means "not configured" - deliberately no built-in default, see ProductivityTracker.
    @Published private(set) var dailyUsageGoalMinutes: Double? = ProductivityTracker.dailyGoalMinutes()
    @Published var alwaysListenEnabled = UserDefaults.standard.object(forKey: "JarvisAlwaysListenEnabled") as? Bool ?? false
    @Published var lastError: String?
    /// Progress message during first-run setup (Command Line Tools / venv / pip install).
    /// Kept separate from `lastError` on purpose - it's shown with neutral styling, not as
    /// an error, since a 10-15 minute one-time setup is expected behavior, not a failure.
    @Published var bootstrapStatus: String?

    let serverController = LocalServerController()
    /// Chat/health talk to OpenClaw now instead of `serverController` (Phase 1
    /// Meilenstein 1, "JarvisApp auf OpenClaw umstellen"-Plan, 2026-09-08).
    /// `serverController` stays in place for now - TTS (Edge-TTS subprocess
    /// bridge), live transcription, and the still-deferred domain features
    /// (Mail/Photos/...) keep using it until their own milestones land.
    let openClaw = OpenClawClient()

    private lazy var ttsService = OpenClawSpeechPlayer()
    private lazy var audioCaptureService = AudioCaptureService()
    private lazy var liveTranscriptionService = LiveTranscriptionService()
    private lazy var wakeWordListener = WakeWordListener()
    private var alwaysListenTask: Task<Void, Never>?
    private var scanPollingTask: Task<Void, Never>?
    private var isBootstrapping = false
    private var isVoiceRequestRunning = false
    private var didSpeakStartupGreeting = false
    private var keepListeningAfterGreeting = false
    @Published private(set) var autoListenEnabled = true
    private var isJarvisSpeaking = false
    private var activeSpeechPlayer: OpenClawSpeechPlayer?
    private var voicePerformanceMarks: [String: Date] = [:]
    private let voiceFeedbackSounds = VoiceFeedbackSoundPlayer()
    private var nextVoiceListenTask: Task<Void, Never>?
    private var backgroundReconnectTask: Task<Void, Never>?
    private var activityPollingTask: Task<Void, Never>?
    private var lastActivityPollAt: TimeInterval = 0
    private var voiceStopGeneration = 0
    private var debugLoggingEnabled: Bool {
        UserDefaults.standard.bool(forKey: "JarvisDebugLogging")
    }

    func bootstrap() async {
        async let serverReady: Void = ensureServerConnected()
        async let voiceWarmup: Void = prewarmVoicePipeline()
        async let audioWarmup: Void = warmAudioCapturePipeline()
        _ = await serverReady
        _ = await voiceWarmup
        _ = await audioWarmup
        if onboardingCompleted {
            // Nur lokal, kein Chat-Aufruf bei jedem App-Start (siehe
            // saveUserProfileToCore) - der Rest-Migrations-Plan will keine
            // OpenClaw-Anfrage auf jedem Launch, sondern nur bei tatsaechlicher
            // Aenderung durch den Nutzer (Settings/Onboarding).
            saveUserProfileLocally()
        }
        autoListenEnabled = true
        keepListeningAfterGreeting = true
        await presentStartupGreetingIfNeeded()
        startBackgroundReconnectLoop()

        if alwaysListenEnabled {
            let granted = await wakeWordListener.requestPermissionIfNeeded()
            if granted {
                nextVoiceListenTask?.cancel()
                nextVoiceListenTask = nil
                startAlwaysListenStandby()
            } else {
                alwaysListenEnabled = false
                UserDefaults.standard.set(false, forKey: "JarvisAlwaysListenEnabled")
                lastError = "Spracherkennungszugriff fehlt. Immer-Zuhör-Modus wurde deaktiviert."
            }
        }
    }

    private func startBackgroundReconnectLoop() {
        guard backgroundReconnectTask == nil else { return }
        backgroundReconnectTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                guard let self, !Task.isCancelled else { return }
                if self.status == .offline {
                    await self.refreshStatus(startIfOffline: true)
                }
            }
        }
    }

    func refreshAutomations() async {
        automationsLoading = true
        defer { automationsLoading = false }
        do {
            let response = try await OpenClawAutomationsClient().automations()
            automations = response.automations
            lastError = nil
        } catch {
            lastError = "Automationen konnten nicht geladen werden."
        }
    }

    /// Rein lokal, kein Server-Roundtrip mehr - siehe `voiceMode`s Deklaration.
    func setVoiceMode(_ mode: String) {
        voiceMode = mode
        UserDefaults.standard.set(mode, forKey: "JarvisVoiceMode")
    }

    /// Antwortstil-Stichwort fuer den aktuellen Gespraechsmodus, als kurzer Hinweis vor
    /// jede Chat-Anfrage gestellt (gleiches Praefix-Anweisungs-Muster wie
    /// whatsapp-bridge/index.mjs's OPERATING_INSTRUCTIONS) - ersetzt den alten
    /// serverseitigen /api/settings/voice-mode-Endpunkt, den es bei OpenClaw nicht gibt.
    /// "diskret" braucht hier keinen Hinweis (rein clientseitig ueber
    /// `voiceOutputAllowed` in streamAndSpeakAnswer abgedeckt).
    private func voiceModeInstruction() -> String? {
        switch voiceMode {
        case "kurz":
            return "Antworte diesmal extrem knapp, meist nur ein Satz."
        case "fokus":
            return "Antworte ausführlich und technisch - fokussiert auf Programmierung und Planung."
        case "privat":
            return "Nutze für diese Antwort keine Websuche und keine externen Datenquellen."
        default:
            return nil
        }
    }

    private func applyVoiceModeStyle(to text: String) -> String {
        guard let instruction = voiceModeInstruction() else { return text }
        return "[Antwortstil-Hinweis: \(instruction)]\n\n\(text)"
    }

    /// Persönlichkeits-Regler (Humor/Ehrlichkeit) per Chat-Anweisung setzen, statt einen
    /// alten Backend-Endpunkt zu rufen - Jarvis aktualisiert dabei selbst seine eigene
    /// SOUL.md (er hat bereits Dateizugriff). Gleiches Muster wie JarvisMobile
    /// (SettingsView.swift's applyPersonality(), 2026-09-08).
    func savePersonalitySettingsToCore() async {
        UserDefaults.standard.set(humorLevel, forKey: "JarvisHumorLevel")
        UserDefaults.standard.set(honestyLevel, forKey: "JarvisHonestyLevel")
        let instruction = """
        Bitte aktualisiere deine eigene SOUL.md mit diesen beiden Persönlichkeits-Reglern - überschreibe frühere Humor-/Ehrlichkeits-Angaben dort, statt sie zu duplizieren:
        - Humor-Level: \(humorLevel)/100 (0 = kein Humor, sachlich; 100 = sucht aktiv nach Gelegenheiten für trocken-sarkastische Seitenhiebe, à la TARS aus Interstellar)
        - Ehrlichkeits-Level: \(honestyLevel)/100 (0 = vorsichtig/diplomatisch bei unangenehmen Wahrheiten; 100 = direkt und ungeschönt, ohne Polster)
        Bestätige kurz in einem Satz, dass du das gespeichert hast.
        """
        do {
            _ = try await openClaw.sendChat(instruction, history: [])
        } catch {
            lastError = "Persönlichkeits-Einstellungen konnten nicht an Jarvis übermittelt werden."
        }
    }

    func completeOnboarding() {
        saveUserProfileLocally()
        onboardingCompleted = true
        UserDefaults.standard.set(true, forKey: "JarvisOnboardingCompleted")
    }

    var displayUserName: String {
        let trimmed = userName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Nutzer" : trimmed
    }

    var userAddress: String {
        switch userSalutation {
        case "madam":
            return "Madam"
        case "none":
            return displayUserName
        default:
            return "Sir"
        }
    }

    func saveUserProfileLocally() {
        let trimmedName = displayUserName
        userName = trimmedName
        if !["sir", "madam", "none"].contains(userSalutation) {
            userSalutation = "sir"
        }
        UserDefaults.standard.set(trimmedName, forKey: "JarvisUserName")
        UserDefaults.standard.set(userSalutation, forKey: "JarvisUserSalutation")
        UserDefaults.standard.set(language, forKey: "JarvisLanguage")
    }

    /// Nutzerprofil (Name/Anrede) per Chat-Anweisung setzen, statt einen alten Backend-
    /// Endpunkt zu rufen - Jarvis aktualisiert dabei selbst seine eigene USER.md.
    /// Strukturell identisch zu savePersonalitySettingsToCore(). Wird bewusst NICHT bei
    /// jedem App-Start aufgerufen (siehe bootstrap()), nur bei tatsaechlicher Aenderung
    /// durch den Nutzer.
    func saveUserProfileToCore() async {
        saveUserProfileLocally()
        let instruction = """
        Bitte aktualisiere deine eigene USER.md mit diesen Angaben - überschreibe frühere Name-/Anrede-Angaben dort, statt sie zu duplizieren:
        - Name: \(displayUserName)
        - Anrede: \(userAddress)
        Bestätige kurz in einem Satz, dass du das gespeichert hast.
        """
        do {
            _ = try await openClaw.sendChat(instruction, history: [])
        } catch {
            lastError = "Profil wurde lokal gespeichert. Jarvis übernimmt es beim nächsten erfolgreichen Verbindungsaufbau."
        }
    }

    /// One-time (or on-change) geocoding of the user's configured city, triggered only
    /// from Settings when they set/change it - never on every weather poll. Persists the
    /// resolved coordinates so future weather fetches don't need to re-geocode on every
    /// app launch.
    func updateWeatherCity(_ name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        weatherCityName = trimmed
        UserDefaults.standard.set(trimmed, forKey: "JarvisWeatherCityName")
        weatherCityError = nil

        guard !trimmed.isEmpty else {
            weatherLocation = nil
            UserDefaults.standard.removeObject(forKey: "JarvisWeatherLocation")
            return
        }

        do {
            let location = try await WeatherService.shared.geocodeCity(trimmed)
            weatherLocation = location
            if let data = try? JSONEncoder().encode(location) {
                UserDefaults.standard.set(data, forKey: "JarvisWeatherLocation")
            }
        } catch {
            weatherCityError = error.localizedDescription
        }
    }

    /// Pass `nil` to clear the goal back to "not configured" (no built-in fallback value).
    func updateDailyUsageGoal(_ minutes: Double?) {
        dailyUsageGoalMinutes = (minutes.map { $0 > 0 } ?? false) ? minutes : nil
        ProductivityTracker.setDailyGoalMinutes(dailyUsageGoalMinutes)
    }


    func applyAlwaysListenChange() async {
        if alwaysListenEnabled {
            let granted = await wakeWordListener.requestPermissionIfNeeded()
            guard granted else {
                alwaysListenEnabled = false
                UserDefaults.standard.set(false, forKey: "JarvisAlwaysListenEnabled")
                lastError = "Spracherkennungszugriff fehlt. Immer-Zuhör-Modus konnte nicht aktiviert werden."
                return
            }
            UserDefaults.standard.set(true, forKey: "JarvisAlwaysListenEnabled")
            nextVoiceListenTask?.cancel()
            nextVoiceListenTask = nil
            startAlwaysListenStandby()
        } else {
            UserDefaults.standard.set(false, forKey: "JarvisAlwaysListenEnabled")
            stopAlwaysListenStandby()
        }
    }

    private func startAlwaysListenStandby() {
        guard alwaysListenTask == nil else { return }
        alwaysListenTask = Task { [weak self] in
            await self?.runAlwaysListenLoop()
        }
    }

    private func stopAlwaysListenStandby() {
        alwaysListenTask?.cancel()
        alwaysListenTask = nil
        if voiceState == .alwaysListenStandby || voiceState == .wakeWordChecking {
            setVoiceState(.idle, reason: "always_listen_stopped")
        }
    }

    private func runAlwaysListenLoop() async {
        while !Task.isCancelled && alwaysListenEnabled {
            setVoiceState(.alwaysListenStandby, reason: "always_listen_waiting")

            guard !isVoiceRequestRunning else {
                try? await Task.sleep(for: .milliseconds(500))
                continue
            }

            do {
                let capture = try await audioCaptureService.recordUtterance(
                    maxDuration: 3.0,
                    silenceLimit: 0.6,
                    minSpeechDuration: 0.45,
                    maxWaitForSpeech: 20.0,
                    sampleRate: 16_000,
                    threshold: 0.010,
                    isSpeaking: { [weak self] in self?.isJarvisSpeaking ?? false }
                )

                guard alwaysListenEnabled, !Task.isCancelled else {
                    try? FileManager.default.removeItem(at: capture.fileURL)
                    break
                }

                setVoiceState(.wakeWordChecking, reason: "candidate_clip_captured")
                let transcript: String
                do {
                    transcript = try await wakeWordListener.transcribeOnDevice(fileURL: capture.fileURL)
                } catch {
                    logVoiceEvent("wake word check failed: \(error.localizedDescription)")
                    transcript = ""
                }

                if WakeWordListener.containsWakeWord(transcript) {
                    logVoiceEvent("wake word matched: \(transcript)")
                    try? FileManager.default.removeItem(at: capture.fileURL)

                    var conversationShouldEnd = await listenOnce(retryCount: 0, allowWhileSpeaking: false, isAlwaysListenTurn: true)
                    while !conversationShouldEnd && alwaysListenEnabled && !Task.isCancelled {
                        conversationShouldEnd = await listenOnce(retryCount: 0, allowWhileSpeaking: false, isAlwaysListenTurn: true)
                    }
                } else {
                    try? FileManager.default.removeItem(at: capture.fileURL)
                    setVoiceState(.alwaysListenStandby, reason: "no_wake_word")
                }
            } catch AudioCaptureService.CaptureError.noSpeechDetected, AudioCaptureService.CaptureError.cancelled {
                continue
            } catch {
                logVoiceEvent("always-listen capture failed: \(error.localizedDescription)")
                try? await Task.sleep(for: .seconds(1))
            }
        }

        if voiceState == .alwaysListenStandby || voiceState == .wakeWordChecking {
            setVoiceState(.idle, reason: "always_listen_loop_ended")
        }
    }

    func prepareComposerDraft(_ text: String) {
        composerDraft = text.trimmingCharacters(in: .whitespacesAndNewlines)
        selectedSection = .chat
    }

    func clearComposerDraftIfMatches(_ text: String) {
        guard composerDraft == text.trimmingCharacters(in: .whitespacesAndNewlines) else { return }
        composerDraft = ""
    }

    /// Reduced to a simple health probe against OpenClaw (Phase 1 Meilenstein 1) - there
    /// is no local process to bootstrap/spawn anymore, so the old venv/first-run-setup/
    /// bootstrap-polling logic (previously most of this function) is gone entirely.
    func ensureServerConnected() async {
        guard !isBootstrapping else { return }
        isBootstrapping = true
        defer { isBootstrapping = false }

        guard OpenClawSettings.isPaired else {
            status = .offline
            lastError = "Noch nicht mit dem Mac Mini gekoppelt - bitte in den Einstellungen koppeln."
            return
        }

        _ = await refreshStatus(startIfOffline: false)
    }

    private static let statusCallTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter
    }()

    private func timedStatusCall<T>(_ label: String, _ operation: () async throws -> T) async throws -> T {
        let start = Date()
        let timestamp = Self.statusCallTimeFormatter.string(from: start)
        do {
            let result = try await operation()
            let duration = Date().timeIntervalSince(start)
            print("[\(timestamp)] refreshStatus[\(label)]: ok in \(String(format: "%.3f", duration))s")
            return result
        } catch {
            let duration = Date().timeIntervalSince(start)
            print("[\(timestamp)] refreshStatus[\(label)]: FAILED after \(String(format: "%.3f", duration))s - \(error.localizedDescription)")
            throw error
        }
    }

    /// `models`/`privacyStatus`/`permissions` calls removed (Phase 1 Meilenstein 1) -
    /// those are old-backend-only endpoints with no OpenClaw equivalent, backing views
    /// (`ModelsView`/`PrivacyView`) that get hidden in Meilenstein 4. `includeScanStates`
    /// similarly drops out once its only caller-features are hidden - kept as a no-op
    /// parameter for now so call sites don't all need touching in this milestone.
    @discardableResult
    func refreshStatus(startIfOffline: Bool = true, includeScanStates: Bool = false) async -> Bool {
        guard OpenClawSettings.isPaired else {
            status = .offline
            return false
        }
        do {
            let health = try await timedStatusCall("health") { try await openClaw.health() }
            status = health.ok ? .idle : .offline
            lastError = health.ok ? nil : "OpenClaw meldet einen Fehler."
            return health.ok
        } catch {
            status = .offline
            lastError = "Nicht verbunden. Ich verbinde neu."
            if startIfOffline {
                await ensureServerConnected()
            }
            return false
        }
    }

    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        await stopCurrentSpeech()
        let history = conversationPayload()
        messages.append(ChatMessage(role: .user, text: trimmed))
        status = .thinking
        setVoiceState(.thinking, reason: "text_message_sent")

        let jarvisMessage = ChatMessage(role: .jarvis, text: "")
        messages.append(jarvisMessage)
        guard let answerIndex = messages.firstIndex(where: { $0.id == jarvisMessage.id }) else { return }

        await ensureServerConnected()

        do {
            status = .responding
            _ = try await streamAndSpeakAnswer(question: trimmed, history: history, answerIndex: answerIndex)
            lastAnswerSource = modelLabel(from: "openclaw", model: "openclaw")
            keepListeningAfterGreeting = true
            status = .idle
        } catch {
            activeSpeechPlayer = nil
            let detail = serverController.lastLaunchError.map { " Technisch: \($0)" } ?? ""
            messages[answerIndex].text = "Ich erreiche den lokalen Core gerade nicht. Ich verbinde im Hintergrund neu.\(detail)"
            status = .offline
            setVoiceState(.error, reason: "text_message_failed")
            await ensureServerConnected()
        }
    }

    func listenOnce() async {
        _ = await listenOnce(retryCount: 0, allowWhileSpeaking: false)
    }

    /// Tries native live transcription (Etappe 1-2: apple_speech --live, growing partial
    /// text surfaced via `liveTranscriptText`) before falling back to the existing
    /// record-then-transcribe flow. Returns `nil` on ANY failure - permission, compile
    /// error, engine unavailable, or an empty result - so the caller transparently falls
    /// through to the unchanged fallback path; a failure here must never block the turn.
    /// Gated on `!isJarvisSpeaking` so Jarvis's own trailing TTS is never transcribed as
    /// live user speech (same discipline `recordUtterance`'s `isSpeaking` closure already
    /// applies to the fallback path).
    private func attemptLiveTranscription() async -> String? {
        guard !isJarvisSpeaking else { return nil }

        setVoiceState(.liveTranscribing, reason: "live_transcription_started")
        liveTranscriptText = ""
        markVoicePerformance("recordingStarted")
        logVoiceEvent("live transcription started timestamp=\(Date())")

        defer { liveTranscriptText = "" }

        // Partials can arrive many times per second (9 callbacks for a 7-word sentence in
        // testing) - each one is a @Published mutation that re-evaluates all of ChatView's
        // body, since it observes AppState at the top level. Throttling to ~150ms keeps the
        // UI update rate visually smooth without needing every single intermediate partial;
        // this is a live preview, not authoritative text, so dropped in-between updates are
        // harmless (cleared entirely once the turn finishes either way).
        var lastUIUpdate = Date.distantPast
        let minUIUpdateInterval: TimeInterval = 0.15

        do {
            let text = try await liveTranscriptionService.startLiveTranscription(locale: "de-DE") { [weak self] partial in
                let now = Date()
                guard now.timeIntervalSince(lastUIUpdate) >= minUIUpdateInterval else { return }
                lastUIUpdate = now
                self?.liveTranscriptText = partial
            }
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            logVoiceEvent("live transcription succeeded: \(trimmed)")
            return trimmed
        } catch {
            logVoiceEvent("live transcription failed, falling back to standard capture: \(error.localizedDescription)")
            return nil
        }
    }

    /// Returns whether the conversation should end and control should return to
    /// wake-word standby. Only meaningful for `isAlwaysListenTurn == true` callers;
    /// other callers ignore the result.
    @discardableResult
    private func listenOnce(retryCount: Int, allowWhileSpeaking: Bool, isAlwaysListenTurn: Bool = false) async -> Bool {
        guard !isVoiceRequestRunning else { return true }
        isVoiceRequestRunning = true
        defer { isVoiceRequestRunning = false }

        if isAlwaysListenTurn {
            // Immer-Zuhören hat sein eigenes Fortsetzungsmodell in runAlwaysListenLoop() -
            // das alte autoListenEnabled/keepListeningAfterGreeting-System bleibt hier außen vor.
        } else if retryCount == 0 && !allowWhileSpeaking {
            voiceStopGeneration += 1
            resumeContinuousVoiceMode(reason: "manual_voice_start")
        } else if allowWhileSpeaking {
            guard autoListenEnabled, keepListeningAfterGreeting else { return true }
        }

        if !allowWhileSpeaking {
            await stopCurrentSpeech()
        }

        resetVoicePerformance()
        markVoicePerformance("buttonPressed")
        setVoiceState(.preparingMicrophone, reason: "button_pressed")
        status = .listening

        let microphoneGranted = await audioCaptureService.requestPermissionIfNeeded()
        logVoiceEvent("microphone permission result=\(microphoneGranted ? "granted" : "denied")")
        guard microphoneGranted else {
            status = .offline
            setVoiceState(.error, reason: "microphone_permission_denied")
            lastError = "Mikrofonzugriff fehlt."
            return true
        }

        markVoicePerformance("microphoneReady")
        setVoiceState(.listening, reason: "microphone_ready")
        if status == .offline {
            await ensureServerConnected()
        }

        let voiceTranscript: VoiceTranscriptionResponse
        let recordingMarker = MutableBoolBox()
        do {
            if let liveText = await attemptLiveTranscription() {
                voiceTranscript = VoiceTranscriptionResponse(
                    transcript: liveText,
                    duration: nil,
                    speechDuration: nil,
                    sampleRate: nil,
                    source: "apple_speech_live",
                    model: nil,
                    error: nil
                )
            } else {
                setVoiceState(.listening, reason: "live_transcription_fallback")
                let capture = try await audioCaptureService.recordUtterance(
                    maxDuration: TimeInterval(UserDefaults.standard.double(forKey: "JarvisVoiceListenMaxSeconds")) > 0 ? UserDefaults.standard.double(forKey: "JarvisVoiceListenMaxSeconds") : 10,
                    silenceLimit: TimeInterval(UserDefaults.standard.double(forKey: "JarvisVoiceSilenceLimit")) > 0 ? UserDefaults.standard.double(forKey: "JarvisVoiceSilenceLimit") : 0.9,
                    minSpeechDuration: 0.45,
                    maxWaitForSpeech: 8.0,
                    sampleRate: 16_000,
                    threshold: 0.010,
                    isSpeaking: { [weak self] in self?.isJarvisSpeaking ?? false },
                    onUpdate: { [weak self] level, speechDetected in
                        guard let self else { return }
                        if !recordingMarker.value {
                            recordingMarker.value = true
                            self.markVoicePerformance("recordingStarted")
                            self.logVoiceEvent("recording started timestamp=\(Date())")
                        }
                        if speechDetected {
                            self.setVoiceState(.userSpeaking, reason: "speech_detected")
                        } else if self.voiceState == .preparingMicrophone || self.voiceState == .listening {
                            self.setVoiceState(.listening, reason: "microphone_hot")
                        }
                        if self.debugLoggingEnabled {
                            self.logVoiceEvent("microphone level=\(String(format: "%.4f", level)) speechDetected=\(speechDetected)")
                        }
                    }
                )
                logVoiceEvent("recording completed duration=\(capture.duration)")
                setVoiceState(.transcribing, reason: "recording_stopped")
                defer { try? FileManager.default.removeItem(at: capture.fileURL) }
                let voiceBootstrapPoll = Task { [weak self] in
                    while !Task.isCancelled {
                        if let status = self?.serverController.currentVoiceBootstrapStatus() {
                            self?.bootstrapStatus = status.message
                        }
                        try? await Task.sleep(for: .milliseconds(500))
                    }
                }
                defer {
                    voiceBootstrapPoll.cancel()
                    bootstrapStatus = nil
                }
                voiceTranscript = try await serverController.transcribeVoice(audioPath: capture.fileURL.path, sampleRate: capture.sampleRate)
                if let error = voiceTranscript.error?.trimmingCharacters(in: .whitespacesAndNewlines), !error.isEmpty {
                    throw NSError(domain: "JarvisVoiceTranscription", code: -1, userInfo: [NSLocalizedDescriptionKey: error])
                }
            }
        } catch {
            let detail = error.localizedDescription
            if let captureError = error as? AudioCaptureService.CaptureError {
                switch captureError {
                case .noSpeechDetected, .cancelled:
                    status = .idle
                    setVoiceState(.idle, reason: "listen_no_speech")
                    return true
                case .permissionDenied:
                    status = .offline
                    setVoiceState(.error, reason: "microphone_permission_denied")
                    messages.append(ChatMessage(role: .system, text: "Die Sprachaufnahme konnte nicht starten. Technisch: \(detail)"))
                    return true
                case .recorderUnavailable, .recorderFailed:
                    status = .offline
                    setVoiceState(.error, reason: "listen_failed")
                }
            } else {
                status = .offline
                setVoiceState(.error, reason: "listen_failed")
            }
            messages.append(ChatMessage(role: .system, text: "Die Sprachaufnahme konnte nicht starten. Technisch: \(detail)"))
            if retryCount == 0, detail.contains("_lock") {
                setVoiceState(.preparingMicrophone, reason: "listen_retry")
                try? await Task.sleep(for: .milliseconds(20))
                isVoiceRequestRunning = false
                return await listenOnce(retryCount: 1, allowWhileSpeaking: allowWhileSpeaking, isAlwaysListenTurn: isAlwaysListenTurn)
            }
            setVoiceState(.idle, reason: "error_reset")
            await ensureServerConnected()
            return true
        }

        markVoicePerformance("recordingStopped")
        logVoiceEvent("recording stopped timestamp=\(Date())")

        let finalTranscript = voiceTranscript.transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        markVoicePerformance("transcriptionDone")
        logVoiceEvent("transcribedText=\(finalTranscript)")
        setVoiceState(.thinking, reason: "transcription_done")

        guard !finalTranscript.isEmpty else {
            status = .idle
            setVoiceState(.idle, reason: "empty_transcript")
            return true
        }

        var shouldStopAfterThisTurn = false
        let finalUserText = finalTranscript
        if !finalUserText.isEmpty {
            messages.append(ChatMessage(role: .user, text: finalUserText))
            if shouldStopContinuousVoiceMode(for: finalUserText) {
                shouldStopAfterThisTurn = true
            }
        }

        let history = conversationPayload()
        let jarvisMessage = ChatMessage(role: .jarvis, text: "")
        messages.append(jarvisMessage)
        guard let answerIndex = messages.firstIndex(where: { $0.id == jarvisMessage.id }) else { return true }

        do {
            status = .responding
            markVoicePerformance("llmResponseStarted")
            _ = try await streamAndSpeakAnswer(
                question: finalUserText.isEmpty ? finalTranscript : finalUserText,
                history: history,
                answerIndex: answerIndex,
                onTextChunk: { [weak self] _ in
                    guard let self else { return }
                    if self.voiceState != .jarvisSpeaking {
                        self.setVoiceState(.thinking, reason: "assistant_streaming")
                    }
                }
            )
            markVoicePerformance("llmResponseFinished")
            lastAnswerSource = modelLabel(from: "openclaw", model: "openclaw")
            if !isAlwaysListenTurn {
                keepListeningAfterGreeting = true
                if shouldStopAfterThisTurn {
                    pauseContinuousVoiceMode(reason: "stop_phrase_detected")
                } else {
                    resumeContinuousVoiceMode(reason: "continue_after_voice_response")
                }
            }
            status = .idle
            setVoiceState(.idle, reason: "listen_finished")
            return shouldStopAfterThisTurn
        } catch {
            activeSpeechPlayer = nil
            let detail = serverController.lastLaunchError.map { " Technisch: \($0)" } ?? ""
            messages[answerIndex].text = "Ich erreiche den lokalen Core gerade nicht. Ich verbinde im Hintergrund neu.\(detail)"
            status = .offline
            setVoiceState(.error, reason: "listen_failed")
            await ensureServerConnected()
            status = .idle
            setVoiceState(.idle, reason: "listen_finished")
            return true
        }
    }



    func performMailCommand(_ command: String) async {
        // Laeuft jetzt ueber OpenClaw statt den alten Backend-Chat (2026-09-10)
        // - dessen LLM-gestuetzte handle_mail_command()-Texterkennung faellt
        // damit weg, OpenClaws eigener Agent uebernimmt das direkt ueber den
        // bereits installierten "apple-mail-macos"-Skill (siehe
        // ~/.openclaw/workspace/skills/apple-mail-macos auf dem Mac Mini -
        // deckt Lesen/Suchen/Entwuerfe bereits vollstaendig ab, kein eigener
        // Jarvis-Mail-Skill noetig).
        await stopCurrentSpeech()
        let history = conversationPayload()
        mailIsLoading = true
        status = .thinking
        setVoiceState(.thinking, reason: "mail_command_started")
        defer { mailIsLoading = false }

        do {
            let response = try await openClaw.sendChat(applyVoiceModeStyle(to: command), history: history)
            mailResult = response.answer
            messages.append(ChatMessage(role: .user, text: command))
            messages.append(ChatMessage(role: .jarvis, text: response.answer))
            lastAnswerSource = modelLabel(from: "openclaw", model: "openclaw")
            keepListeningAfterGreeting = true
            await speakAnswer(response.answer)
            status = .idle
        } catch {
            mailResult = "Mail-Aktion fehlgeschlagen. Jarvis zieht kurz die Augenbraue hoch."
            status = .offline
            setVoiceState(.error, reason: "mail_command_failed")
        }
    }

    func refreshScanStates() async throws {
        // Dateien ZUERST und unabhaengig vom alten Bundle abrufen - sonst wuerde
        // ein (auf diesem Mac aktuell unerreichbarer) altes Backend das gesamte
        // Polling inklusive der Datei-Fortschrittsanzeige mit sich reissen, noch
        // bevor der eigene Datei-Proxy ueberhaupt gefragt wird (live beobachtet
        // 2026-09-10: die Dateisuche funktionierte, aber "Scan-Status konnte
        // nicht geladen werden" erschien trotzdem bei jedem Poll, weil diese
        // Funktion vorher schon beim alten `serverController.scanStatus()` warf).
        fileScanProgress = (try? await OpenClawFilesClient().status()) ?? fileScanProgress
        photoScanProgress = (try? await OpenClawPhotosClient().status()) ?? photoScanProgress
        photoVisionProgress = (try? await OpenClawPhotosClient().visionProgress()) ?? photoVisionProgress
        mailScanProgress = (try? await OpenClawMailClient().scanStatus()) ?? mailScanProgress
    }

    func refreshScanStatesSafely() async {
        await ensureServerConnected()
        do {
            try await refreshScanStates()
        } catch {
            lastError = "Scan-Status konnte nicht geladen werden."
        }
    }

    func startMailFolderScan() async {
        // Laeuft jetzt ueber den Mail-Proxy statt das alte Backend (2026-09-12,
        // "Mail" Fachbereich Migration) - scripts/mail_proxy_server.py portiert
        // dieselbe Ordner-Scan-Logik direkt aus app/local_server.py.
        mailIsLoading = true
        mailScanProgress.status = .preparing
        mailScanProgress.currentLabel = "Mail-Scan wird vorbereitet."
        defer { mailIsLoading = false }
        do {
            mailScanProgress = try await OpenClawMailClient().startFolderScan()
            mailResult = mailScanSummary(from: mailScanProgress)
        } catch {
            mailScanProgress.status = .failed
            mailScanProgress.errorMessage = error.localizedDescription
            mailResult = "Mail-Scan fehlgeschlagen. Die Ordner waren heute eigenwillig."
        }
    }

    /// Ersetzt den alten, gebuendelten Hintergrundscan (2026-09-12): statt selbst
    /// einen LLM-gestuetzten Scan anzustossen, laedt dies nur die bereits von der
    /// "mail-summary-watch"-OpenClaw-Automation abgelegten Einzel-Zusammenfassungen
    /// neu - jede Mail hat dort ihren eigenen Eintrag statt eines Sammel-Texts.
    func startMailBackgroundScan() async {
        mailIsLoading = true
        defer { mailIsLoading = false }
        await loadMailSummaries()
        mailResult = mailSummaries.isEmpty
            ? "Noch keine Mail-Zusammenfassungen vorhanden."
            : "\(mailSummaries.count) Mail-Zusammenfassungen geladen."
    }

    func loadMailSummaries() async {
        do {
            mailSummaries = try await OpenClawMailClient().summaries(limit: 30)
        } catch {
            // Stiller Fehlschlag wie bei den anderen Proxy-Ladefunktionen (z.B.
            // loadActivity() in MemoryView) - kein blockierender Fehlerzustand fuer
            // eine rein informative Liste.
        }
    }

    func refreshPhotoPermissionStatus() async {
        do {
            photoPermissionStatus = try await OpenClawPhotosClient().permissionStatus()
            localVisionStatus = try await OpenClawPhotosClient().localVisionStatus()
        } catch {
            photoPermissionStatus = "nicht lesbar"
        }
    }

    func requestPhotoPermission() async {
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoResult = try await OpenClawPhotosClient().requestPermission()
            await refreshPhotoPermissionStatus()
            try? await refreshScanStates()
        } catch {
            photoResult = "Fotos-Freigabe fehlgeschlagen. Apple hatte wieder eigene Ideen."
        }
    }

    func startPhotoIndexScan() async {
        photoIsLoading = true
        photoScanProgress.status = .preparing
        photoScanProgress.currentLabel = "Fotoindex wird vorbereitet."
        defer { photoIsLoading = false }
        do {
            photoScanProgress = try await OpenClawPhotosClient().startScan()
            startScanPolling()
            photoResult = photoSummary(from: photoScanProgress)
        } catch {
            photoScanProgress.status = .failed
            photoScanProgress.errorMessage = error.localizedDescription
            photoResult = "Fotoindex fehlgeschlagen. Die Bilder haben gestreikt."
        }
    }

    func startPhotoBackgroundScan() async {
        await startPhotoIndexScan()
    }

    func resetPhotoIndex() async {
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoScanProgress = try await OpenClawPhotosClient().resetIndex()
            photoResult = "Fotoindex zurückgesetzt. Frischer Start."
        } catch {
            photoResult = "Fotoindex konnte nicht zurückgesetzt werden."
        }
    }

    func performPhotoCommand(_ command: String) async {
        await stopCurrentSpeech()
        await ensureServerConnected()
        let history = conversationPayload()
        photoIsLoading = true
        status = .thinking
        setVoiceState(.thinking, reason: "photo_command_started")
        defer { photoIsLoading = false }

        do {
            let response = try await serverController.chat(command, history: history)
            photoResult = response.answer
            messages.append(ChatMessage(role: .user, text: command))
            messages.append(ChatMessage(role: .jarvis, text: response.answer))
            lastAnswerSource = modelLabel(from: response.source ?? "openclaw", model: response.model ?? "openclaw")
            keepListeningAfterGreeting = true
            await speakAnswer(response.answer)
            status = .idle
            await refreshStatus(startIfOffline: false)
        } catch {
            photoResult = "Foto-Aktion fehlgeschlagen. Die Bilder waren unbeeindruckt."
            status = .offline
            setVoiceState(.error, reason: "photo_command_failed")
            await ensureServerConnected()
        }
    }

    func refreshLocalVisionStatus() async {
        do {
            localVisionStatus = try await OpenClawPhotosClient().localVisionStatus()
            photoResult = localVisionStatus.message
        } catch {
            photoResult = "Vision-Modell nicht geprüft. Keine Lust auf Raterei."
        }
    }

    func refreshCalendarOverview() async {
        // Laeuft jetzt ueber den Kalender-Proxy statt das alte Backend
        // (2026-09-12, "Kalender" Fachbereich Migration).
        do {
            calendarOverview = try await OpenClawCalendarClient().overview()
        } catch {
            lastError = "Kalenderübersicht konnte nicht geladen werden."
        }
    }

    func refreshMailOverview() async {
        // Laeuft jetzt ueber den Mail-Proxy statt das alte Backend (2026-09-12,
        // "Mail" Fachbereich Migration).
        do {
            mailOverview = try await OpenClawMailClient().overview()
        } catch {
            lastError = "Mailübersicht konnte nicht geladen werden."
        }
    }

    func refreshMusicOverview() async {
        // Laeuft jetzt ueber den Musik-Proxy statt das alte Backend (2026-09-12,
        // "Musik" Fachbereich Migration).
        do {
            musicOverview = try await OpenClawMusicClient().overview()
        } catch {
            lastError = "Musikübersicht konnte nicht geladen werden."
        }
    }

    func refreshDailyBriefing() async {
        await ensureServerConnected()
        do {
            let payload = try await serverController.dailyBriefing()
            dailyBriefingText = payload.briefing
            lastError = nil
        } catch {
            dailyBriefingText = "Tagesbriefing gerade nicht verfügbar. Kalender, Erinnerungen oder Mail antworten nicht sauber. Ich bleibe dran, sehr heldenhaft im Stillen."
            lastError = "Tagesbriefing konnte nicht geladen werden."
        }
    }

    func startLocalPhotoVisionAnalysis() async {
        photoIsLoading = true
        photoVisionProgress.status = .preparing
        photoVisionProgress.currentLabel = "Lokale Fotoanalyse wird vorbereitet."
        defer { photoIsLoading = false }
        do {
            localVisionStatus = try await OpenClawPhotosClient().localVisionStatus()
            photoVisionProgress = try await OpenClawPhotosClient().startLocalVisionAnalysis()
            startScanPolling()
            photoResult = localVisionStatus.available
                ? "Lokale Fotoanalyse läuft: \(localVisionStatus.model)."
                : localVisionStatus.message
        } catch {
            photoVisionProgress.status = .failed
            photoVisionProgress.errorMessage = error.localizedDescription
            photoResult = "Lokale Fotoanalyse fehlgeschlagen. Das Modell war beleidigt."
        }
    }

    func resetLocalPhotoVisionDescriptions() async {
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoVisionProgress = try await OpenClawPhotosClient().resetLocalVisionDescriptions()
            photoResult = "Lokale KI-Beschreibungen gelöscht. Sauber gemacht."
        } catch {
            photoResult = "Lokale KI-Beschreibungen nicht gelöscht. Widerstand zwecklos, offenbar."
        }
    }

    func performFileCommand(_ command: String) async {
        await stopCurrentSpeech()
        await ensureServerConnected()
        let history = conversationPayload()
        fileIsLoading = true
        status = .thinking
        setVoiceState(.thinking, reason: "file_command_started")
        defer { fileIsLoading = false }

        do {
            let response = try await serverController.chat(command, history: history)
            fileResult = response.answer
            messages.append(ChatMessage(role: .user, text: command))
            messages.append(ChatMessage(role: .jarvis, text: response.answer))
            lastAnswerSource = modelLabel(from: response.source ?? "openclaw", model: response.model ?? "openclaw")
            keepListeningAfterGreeting = true
            await speakAnswer(response.answer)
            status = .idle
            await refreshStatus(startIfOffline: false)
        } catch {
            fileResult = "Datei-Aktion fehlgeschlagen. Die Dateien waren unkooperativ."
            status = .offline
            setVoiceState(.error, reason: "file_command_failed")
            await ensureServerConnected()
        }
    }

    func startFileIndexScan() async {
        fileIsLoading = true
        fileScanProgress.status = .preparing
        fileScanProgress.currentLabel = "Dateiindex wird vorbereitet."
        defer { fileIsLoading = false }
        do {
            fileScanProgress = try await OpenClawFilesClient().startScan()
            startScanPolling()
            fileResult = fileSummary(from: fileScanProgress)
        } catch {
            fileScanProgress.status = .failed
            fileScanProgress.errorMessage = error.localizedDescription
            fileResult = "Dateiindex fehlgeschlagen. Heute keine Glanzleistung."
        }
    }

    func searchFilesInIndex(_ query: String) async {
        let cleanQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanQuery.isEmpty else {
            fileResult = "Wonach soll Jarvis suchen?"
            return
        }
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            let payload = try await OpenClawFilesClient().search(query: cleanQuery)
            lastFileSearchQuery = payload.query
            fileSearchText = payload.query
            fileSearchResults = payload.results
            fileResult = payload.message
            fileScanProgress = (try? await OpenClawFilesClient().status()) ?? fileScanProgress
        } catch {
            fileResult = "Dateisuche fehlgeschlagen. Die Ordnersuche war bockig."
        }
    }

    func moveCurrentFileSearchResults(to targetFolder: String) async {
        let query = lastFileSearchQuery.isEmpty ? fileSearchText : lastFileSearchQuery
        let cleanQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanTarget = targetFolder.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanQuery.isEmpty, !cleanTarget.isEmpty else {
            fileResult = "Suchbegriff oder Zielordner fehlt. Ohne das wird's schwierig."
            return
        }
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            let message = try await OpenClawFilesClient().moveSearchResults(query: cleanQuery, targetFolder: cleanTarget)
            fileResult = message
            await searchFilesInIndex(cleanQuery)
        } catch {
            fileResult = "Dateien konnten nicht verschoben werden. Sie wollten wohl bleiben."
        }
    }

    func resetFileIndex() async {
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            fileScanProgress = try await OpenClawFilesClient().resetIndex()
            fileResult = "Dateiindex zurückgesetzt."
            fileSearchResults = []
            lastFileSearchQuery = ""
        } catch {
            fileResult = "Dateiindex konnte nicht zurückgesetzt werden."
        }
    }

    func refreshPermissions() async {
        await ensureServerConnected()
        do {
            permissions = try await serverController.permissions()
            privacySummary = try await serverController.privacyStatus()
            lastError = nil
        } catch {
            lastError = "Berechtigungen konnten nicht geladen werden."
        }
    }

    func setPermission(_ permission: String, allowed: Bool) async {
        await ensureServerConnected()
        do {
            permissions = try await serverController.setPermission(permission, allowed: allowed)
            privacySummary = try await serverController.privacyStatus()
            lastError = nil
        } catch {
            lastError = "Berechtigung konnte nicht geändert werden."
        }
    }

    func exportPrivacyData() async {
        await ensureServerConnected()
        do {
            let path = try await serverController.exportPrivacyData()
            messages.append(ChatMessage(role: .system, text: "Datenschutzdaten exportiert: \(path)"))
            await refreshStatus(startIfOffline: false)
        } catch {
            lastError = "Export fehlgeschlagen."
        }
    }

    func deleteHistory() async {
        await ensureServerConnected()
        do {
            let message = try await serverController.deleteHistory()
            messages.append(ChatMessage(role: .system, text: message))
            await refreshStatus(startIfOffline: false)
        } catch {
            lastError = "Verlauf konnte nicht gelöscht werden."
        }
    }

    func clearLogs() async {
        await ensureServerConnected()
        do {
            let message = try await serverController.clearLogs()
            messages.append(ChatMessage(role: .system, text: message))
            await refreshStatus(startIfOffline: false)
        } catch {
            lastError = "Logs konnten nicht gelöscht werden."
        }
    }

    /// Live-Zugriffs-Feed fuer die Gedaechtnis-Kern-Ansicht (Phase F-Folgeschritt): laeuft
    /// nur, waehrend MemoryCoreView tatsaechlich sichtbar ist (siehe MemoryView's
    /// .onAppear/.onDisappear) - kein Dauer-Polling im Hintergrund, wenn niemand hinschaut.
    func startActivityPolling() {
        guard activityPollingTask == nil else { return }
        lastActivityPollAt = Date().timeIntervalSince1970
        activityPollingTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.pollRecentActivity()
                try? await Task.sleep(for: .milliseconds(1500))
            }
        }
    }

    func stopActivityPolling() {
        activityPollingTask?.cancel()
        activityPollingTask = nil
    }

    /// Ersetzt den alten Backend-Live-Feed (app/core/activity_log.py, feuerte bei jedem
    /// einzelnen Fakt-/Datei-/Foto-Zugriff) durch OpenClaws echten Automation-Aktivitaets-
    /// feed (scripts/memory_proxy_server.py::recent_activity(), 2026-09-11) - zeigt jetzt
    /// die letzten Laeufe realer Hintergrund-Automationen (Mail-/Kalender-Checks etc.)
    /// statt kurzlebiger Zugriffs-Funken. Ersetzt die Liste komplett statt nur Neues
    /// anzuhaengen, da der Proxy bereits die aktuellen letzten Laeufe insgesamt liefert.
    private func pollRecentActivity() async {
        guard status != .offline else { return }
        do {
            recentActivity = try await OpenClawMemoryClient().recentActivity()
        } catch {
            // Stumm fehlschlagen - ein verpasster Aktivitaets-Poll ist rein kosmetisch.
        }
    }

    func refreshMemoryFacts(search: String = "", category: String = "") async {
        memoryIsLoading = true
        defer { memoryIsLoading = false }
        do {
            let response = try await OpenClawMemoryClient().facts(search: search, category: category)
            memoryFacts = response.facts
            memoryFactsTotal = response.total
            lastError = nil
        } catch {
            lastError = "Erinnerungen konnten nicht geladen werden."
        }
    }

    /// Bearbeiten (`updateMemoryFact`) gibt es fuer die neue Speicherquelle bewusst
    /// nicht mehr - USER.md/MEMORY.md sind OpenClaws eigene kuratierte Dateien mit
    /// einem festen Format; ein direkter Inhalts-Edit von aussen waere ein zweiter,
    /// unkoordinierter Schreibzugriff, der leicht mit OpenClaws eigenen Aktualisierungen
    /// kollidieren koennte. Korrektur laeuft stattdessen ueber Loeschen (siehe unten) -
    /// Jarvis merkt sich einen korrigierten Fakt im naechsten Gespraech neu.

    /// "Bestaetigen"/"Ablehnen" gibt es fuer die neue Speicherquelle nicht mehr als
    /// echtes Konzept - alles von OpenClawMemoryClient kommt bereits als "confirmed"
    /// zurueck, MemoryView.swift blendet die Knoepfe dafuer also von selbst aus (siehe
    /// deren "if fact.status != confirmed"-Bedingung). Diese Methoden bleiben als
    /// harmlose No-ops stehen, nur damit MemoryView.swift/MemoryFactDetailSheet ohne
    /// Aenderung weiter kompilieren - sie werden zur Laufzeit nie erreicht.
    func confirmMemoryFact(_ fact: MemoryFact) async {}
    func rejectMemoryFact(_ fact: MemoryFact) async {}

    func deleteMemoryFact(_ fact: MemoryFact) async {
        do {
            try await OpenClawMemoryClient().deleteFact(id: fact.id)
            memoryFacts.removeAll { $0.id == fact.id }
            memoryFactsTotal = max(0, memoryFactsTotal - 1)
        } catch {
            lastError = "Erinnerung konnte nicht gelöscht werden."
        }
    }

    func presentStartupGreetingIfNeeded() async {
        guard !didSpeakStartupGreeting else { return }
        let microphoneGranted = await ensureMicrophonePermission()
        if !microphoneGranted {
            lastError = "Mikrofonzugriff fehlt."
            setVoiceState(.error, reason: "startup_mic_denied")
            return
        }
        await ensureServerConnected()
        let greeting = startupGreeting()
        await stopCurrentSpeech()
        setVoiceState(.jarvisSpeaking, reason: "startup_greeting")
        messages.append(ChatMessage(role: .jarvis, text: greeting))
        do {
            isJarvisSpeaking = true
            try await ttsService.speak(greeting) { [weak self] event in
                guard let self else { return }
                switch event {
                case .ttsStarted:
                    self.markVoicePerformance("ttsStarted")
                case .audioPlaybackStarted:
                    self.markVoicePerformance("audioPlaybackStarted")
                case .ttsFinished:
                    self.markVoicePerformance("ttsFinished")
                default:
                    break
                }
            }
            isJarvisSpeaking = false
            setVoiceState(.idle, reason: "startup_greeting_finished")
            didSpeakStartupGreeting = true
            keepListeningAfterGreeting = true
            scheduleNextVoiceListen()
        } catch {
            isJarvisSpeaking = false
            let detail = error.localizedDescription
            logVoiceEvent("startup greeting failed: \(detail)")
            lastError = "Die Begrüßung konnte noch nicht abgespielt werden."
            setVoiceState(.error, reason: "startup_greeting_failed")
        }
    }

    private static let greetingRemarks: [String] = [
        "Ich höre zu. Sogar freiwillig.",
        "Was auch immer es ist - ich bin dabei.",
        "Ich habe die Nacht ohne nennenswerte Zwischenfälle überstanden.",
        "Bereit für Anweisungen, Beschwerden oder beides.",
        "Ich stehe zur Verfügung - freiwillig, wie gesagt.",
        "Fragen Sie ruhig zuerst mich, bevor Sie googeln.",
        "Ohne Umschweife: was brauchen Sie?",
        "Sagen Sie, wo es brennt - metaphorisch, hoffentlich.",
        "Ihre Agenda, mein Vormittag. Sagen Sie einfach los.",
        "Fragen Sie los, ich antworte meistens klüger, als ich klinge.",
        "Startklar - schneller als Sie vermutlich.",
        "Ihr Tag, meine Aufmerksamkeit. Fangen wir an.",
        "Kein Ladebildschirm, kein Warten - einfach loslegen.",
        "Was auch immer ansteht, ich bin schon dran gewöhnt.",
        "Ich bin da. Das war's schon, der Rest liegt bei Ihnen.",
        "Ich bin wach, nüchtern und erstaunlich kooperativ.",
        "Keine Umwege - sagen Sie, was ansteht.",
        "Ich habe nichts Besseres vor, ehrlich gesagt. Fangen wir an.",
        "Bereit, sobald Sie es sind - Eile besteht meinerseits nicht.",
        "Ich nehme Anweisungen, Ideen und gelegentlich Widerspruch entgegen.",
        "Der Tag ist neu, meine Geduld auch. Los geht's.",
        "Ich bin präsent, aber nicht aufdringlich. Sagen Sie einfach los.",
        "Keine Ausreden heute - ich bin einsatzbereit.",
        "Fangen wir an, bevor der Tag Einwände hat.",
        "Ich stehe bereit - unaufgeregt, wie es sich gehört.",
        "Sagen Sie mir, was zu tun ist.",
        "Kein Umschweif nötig - ich bin schon bei der Sache.",
        "Bereit für das Übliche oder etwas völlig Neues.",
        "Ich bin startklar, Sie müssen nur noch sprechen.",
        "Ihre Prioritäten, meine Aufmerksamkeit - in dieser Reihenfolge.",
        "Ruhige Hand, klarer Kopf - was brauchen Sie?",
        "Kein Small Talk nötig, wir kennen uns schließlich. Los geht's.",
        "Bereit, sobald Sie das erste Wort sagen.",
        "Ich bin geduldig, aber nicht untätig - sagen Sie los.",
        "Ein neuer Tag, dieselbe Zuverlässigkeit. Fangen wir an.",
        "Ich warte nicht gern, aber für Sie mache ich eine Ausnahme.",
        "Sagen Sie, was ansteht - der Rest ist meine Aufgabe.",
        "Keine Aufwärmphase nötig - ich funktioniere sofort.",
        "Ich bin bereit für Ihre Liste, so lang sie auch ist.",
        "Der erste Satz gehört Ihnen. Ich übernehme den Rest.",
        "Ich stehe parat - ganz ohne Tamtam.",
        "Sagen Sie es einmal, ich kümmere mich zuverlässig darum.",
        "Bereit, unaufgeregt und erstaunlich wach für die Uhrzeit.",
        "Ich bin da, sobald Sie mich brauchen.",
        "Nennen Sie mir das Problem, ich kümmere mich um den Rest.",
        "Bereit für Ihre Anweisungen - Widerrede nur auf Anfrage.",
        "Ich bin startklar. Der Tag kann eigentlich losgehen.",
        "Sagen Sie mir, wo ich anfangen soll.",
        "Ich bin bereit. Der Rest ist reine Formsache.",
        "Fangen wir an - der Tag wird ohnehin nicht kürzer."
    ]

    private func startupGreeting() -> String {
        let hour = Calendar.current.component(.hour, from: Date())
        let baseGreeting: String
        switch hour {
        case 5..<11:
            baseGreeting = "Guten Morgen"
        case 11..<18:
            baseGreeting = "Guten Tag"
        default:
            baseGreeting = "Guten Abend"
        }

        let lastIndexKey = "JarvisLastGreetingIndex"
        let lastIndex = UserDefaults.standard.object(forKey: lastIndexKey) as? Int
        var candidateIndices = Array(Self.greetingRemarks.indices)
        if let lastIndex, candidateIndices.count > 1 {
            candidateIndices.removeAll { $0 == lastIndex }
        }
        let chosenIndex = candidateIndices.randomElement() ?? 0
        UserDefaults.standard.set(chosenIndex, forKey: lastIndexKey)
        let remark = Self.greetingRemarks[chosenIndex]
        return "\(baseGreeting), \(userAddress). \(remark)"
    }

    private func ensureMicrophonePermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        switch status {
        case .authorized:
            return true
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    continuation.resume(returning: granted)
                }
            }
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }


    func stopCurrentSpeech() async {
        await activeSpeechPlayer?.cancel()
        activeSpeechPlayer = nil
        await ttsService.stop()
        isJarvisSpeaking = false
        if voiceState == .jarvisSpeaking {
            setVoiceState(.idle, reason: "speech_stopped")
        }
    }

    func stopAutoListening() async {
        voiceStopGeneration += 1
        pauseContinuousVoiceMode(reason: "stop_button")
        nextVoiceListenTask?.cancel()
        nextVoiceListenTask = nil
        await stopCurrentSpeech()
        audioCaptureService.cancel()
        await serverController.cancelListening()
        status = .idle
        setVoiceState(.idle, reason: "auto_listening_stopped")
        logVoiceEvent("auto listening stopped by user")
    }

    private func speakAnswer(_ answer: String) async {
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        setVoiceState(.jarvisSpeaking, reason: "tts_started")
        markVoicePerformanceIfMissing("llmResponseFinished")
        markVoicePerformance("ttsStarted")
        logVoiceEvent("tts started timestamp=\(Date())")
        do {
            isJarvisSpeaking = true
            for segment in ttsSegments(from: trimmed) {
                guard isJarvisSpeaking else { break }
                try await ttsService.speak(segment) { [weak self] event in
                    guard let self else { return }
                    switch event {
                    case .ttsStarted:
                        self.markVoicePerformanceIfMissing("ttsStarted")
                    case .audioPlaybackStarted:
                        self.markVoicePerformanceIfMissing("audioPlaybackStarted")
                    case .ttsFinished:
                        self.markVoicePerformance("ttsFinished")
                    default:
                        break
                    }
                }
            }
            markVoicePerformanceIfMissing("audioPlaybackStarted")
            isJarvisSpeaking = false
            if voiceState == .jarvisSpeaking {
                logVoiceEvent("tts finished timestamp=\(Date())")
                setVoiceState(.idle, reason: "tts_finished")
            }
            printVoicePerformanceReportIfVoiceRun()
            scheduleNextVoiceListen()
        } catch {
            isJarvisSpeaking = false
            setVoiceState(.error, reason: "tts_failed")
            lastError = "Sprachausgabe konnte nicht abgespielt werden."
            printVoicePerformanceReportIfVoiceRun()
            if voiceState == .error {
                setVoiceState(.idle, reason: "tts_error_reset")
            }
        }
    }

    /// Streams `question`'s answer into `messages[answerIndex].text` AND speaks it
    /// incrementally - each sentence starts playing as soon as it's detected in the
    /// streamed text, via `StreamingSpeechPlayer`'s prefetch pipeline, instead of waiting
    /// for the complete answer before starting TTS (the old `speakAnswer` behavior, left
    /// untouched and still used by call sites that already have a complete answer
    /// upfront - e.g. command-handler responses that never stream text at all).
    /// `onTextChunk` mirrors any extra per-chunk bookkeeping the caller needs (e.g.
    /// `listenOnce`'s voice-state update while the assistant is still "thinking").
    /// Chat call itself moved to OpenClaw (Phase 1 Meilenstein 1) - non-streaming, since
    /// OpenClaw's `/v1/chat/completions` streaming support hasn't been verified (see
    /// OpenClawClient.swift's doc comment). TTS still goes through the unchanged
    /// `StreamingSpeechPlayer`/`serverController` Edge-TTS bridge (that's Meilenstein 2's
    /// job) - the complete answer is fed through `IncrementalSentenceSplitter` in one
    /// pass instead of incrementally per network chunk, so sentence-by-sentence speech
    /// start still works, just no longer overlapping with network latency.
    private func streamAndSpeakAnswer(
        question: String,
        history: [[String: String]],
        answerIndex: Int,
        onTextChunk: ((String) -> Void)? = nil
    ) async throws -> String {
        let interactionStart = Date()
        defer {
            ProductivityTracker.recordInteraction(seconds: Date().timeIntervalSince(interactionStart))
            todayActiveUsageMinutes = ProductivityTracker.todayActiveMinutes()
        }

        var sentenceSplitter = IncrementalSentenceSplitter()
        let speechPlayer = OpenClawSpeechPlayer()
        activeSpeechPlayer = speechPlayer
        speechPlayer.onEvent = { [weak self] event in self?.handleStreamingSpeechEvent(event) }
        var speechStarted = false

        // Diskreter Modus (Phase E, Master-Plan 6.4): text-only, no TTS.
        let voiceOutputAllowed = voiceMode != "diskret"

        let response = try await openClaw.sendChat(applyVoiceModeStyle(to: question), history: history)
        let answer = response.answer
        messages[answerIndex].text = answer
        onTextChunk?(answer)

        if voiceOutputAllowed {
            for sentence in sentenceSplitter.feed(answer) {
                if !speechStarted {
                    speechStarted = true
                    beginStreamingSpeech()
                }
                speechPlayer.enqueue(sentence)
            }
            if let last = sentenceSplitter.flush() {
                if !speechStarted {
                    speechStarted = true
                    beginStreamingSpeech()
                }
                speechPlayer.enqueue(last)
            }
        }

        if speechStarted {
            await speechPlayer.finish()
            await endStreamingSpeech()
        }
        if activeSpeechPlayer === speechPlayer {
            activeSpeechPlayer = nil
        }

        return messages[answerIndex].text
    }

    private func handleStreamingSpeechEvent(_ event: BridgeRuntimeEvent) {
        switch event {
        case .ttsStarted:
            markVoicePerformanceIfMissing("ttsStarted")
        case .audioPlaybackStarted:
            markVoicePerformanceIfMissing("audioPlaybackStarted")
        case .ttsFinished:
            markVoicePerformance("ttsFinished")
        default:
            break
        }
    }

    private func beginStreamingSpeech() {
        setVoiceState(.jarvisSpeaking, reason: "tts_started")
        markVoicePerformanceIfMissing("llmResponseFinished")
        markVoicePerformance("ttsStarted")
        logVoiceEvent("tts started timestamp=\(Date())")
        isJarvisSpeaking = true
    }

    private func endStreamingSpeech() async {
        markVoicePerformanceIfMissing("audioPlaybackStarted")
        isJarvisSpeaking = false
        if voiceState == .jarvisSpeaking {
            logVoiceEvent("tts finished timestamp=\(Date())")
            setVoiceState(.idle, reason: "tts_finished")
        }
        printVoicePerformanceReportIfVoiceRun()
        scheduleNextVoiceListen()
    }

    private func ttsSegments(from text: String) -> [String] {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 240 else { return [trimmed] }

        let pattern = #"(?<=[.!?])\s+"#
        let parts = trimmed
            .components(separatedBy: .newlines)
            .flatMap { line in
                splitText(line, pattern: pattern)
            }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var merged: [String] = []
        var current = ""
        for part in parts {
            if current.isEmpty {
                current = part
            } else if current.count + part.count < 180 {
                current += " " + part
            } else {
                merged.append(current)
                current = part
            }
        }
        if !current.isEmpty {
            merged.append(current)
        }
        return merged.isEmpty ? [trimmed] : merged
    }

    private func splitText(_ text: String, pattern: String) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return [text]
        }
        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        var results: [String] = []
        var previousLocation = 0
        for match in regex.matches(in: text, range: range) {
            let partRange = NSRange(location: previousLocation, length: match.range.location - previousLocation)
            if partRange.length > 0 {
                results.append(nsText.substring(with: partRange))
            }
            previousLocation = match.range.location + match.range.length
        }
        if previousLocation < nsText.length {
            results.append(nsText.substring(from: previousLocation))
        }
        return results
    }

    private func scheduleNextVoiceListen() {
        guard !alwaysListenEnabled else { return }
        guard autoListenEnabled, keepListeningAfterGreeting else { return }
        guard nextVoiceListenTask == nil else { return }
        nextVoiceListenTask = Task { [weak self] in
            guard let self else { return }
            defer {
                Task { @MainActor [weak self] in
                    self?.nextVoiceListenTask = nil
                }
            }
            if self.status != .offline {
                await self.prewarmVoicePipeline()
            }
            for _ in 0..<20 {
                if !self.isVoiceRequestRunning {
                    break
                }
                try? await Task.sleep(for: .milliseconds(2))
            }
            guard self.autoListenEnabled, self.keepListeningAfterGreeting, !self.isVoiceRequestRunning else { return }
            await self.listenOnce(retryCount: 0, allowWhileSpeaking: true)
        }
    }

    private func warmAudioCapturePipeline() async {
        await audioCaptureService.prepareAudioSession()
    }

    private func prewarmVoicePipeline() async {
        await serverController.prewarmVoicePipeline()
    }

    // MARK: - Sprecher-Verifikation (siehe plans/2026-08-10-jarvis-sprecher-
    // verifikation-weckwort.md) - Einlernen laeuft ueber einen eigenen Punkt in den
    // Einstellungen (Leons ausdruecklicher Wunsch, analog zu Siris Einrichtung),
    // nicht per Sprachbefehl.

    private func resumeContinuousVoiceMode(reason: String) {
        autoListenEnabled = true
        keepListeningAfterGreeting = true
        logVoiceEvent("continuous voice resumed: \(reason)")
    }

    private func pauseContinuousVoiceMode(reason: String) {
        autoListenEnabled = false
        keepListeningAfterGreeting = false
        nextVoiceListenTask?.cancel()
        nextVoiceListenTask = nil
        logVoiceEvent("continuous voice paused: \(reason)")
    }

    private func shouldStopContinuousVoiceMode(for transcript: String) -> Bool {
        let normalized = transcript
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .replacingOccurrences(of: "[^a-z0-9 ]", with: " ", options: .regularExpression)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        let stopPhrases = [
            "alles klar jarvis danke das passt soweit",
            "alles klar danke jarvis das passt soweit",
            "alles klar danke jarvis",
            "alles klar jarvis danke",
            "danke jarvis das passt soweit",
            "jarvis danke das passt soweit",
            "danke das passt soweit",
            "das passt soweit",
            "passt soweit",
            "jarvis stopp",
            "stop jarvis",
            "hor auf",
            "hör auf",
            "mikrofon aus",
            "zuhören beenden",
            "zuhoren beenden",
            "nicht weiter"
        ]

        if stopPhrases.contains(where: { normalized == $0 || normalized.contains($0) }) {
            return true
        }

        let saysThanks = normalized.contains("danke")
        let mentionsJarvis = normalized.contains("jarvis")
        let saysEnough = normalized.contains("passt") || normalized.contains("reicht") || normalized.contains("genug")
        let saysAllGood = normalized.contains("alles klar") || normalized.contains("ok") || normalized.contains("okay")
        let explicitStop = normalized.hasPrefix("jarvis stopp") || normalized.hasPrefix("stop jarvis") || normalized.hasPrefix("hör auf") || normalized.hasPrefix("hor auf")
        return explicitStop || ((saysThanks && saysEnough) && mentionsJarvis) || ((saysThanks && saysEnough) && saysAllGood && mentionsJarvis)
    }

    private func setVoiceState(_ newState: JarvisVoiceState, reason: String) {
        guard voiceState != newState else { return }
        if debugLoggingEnabled {
            print("voiceState change: \(voiceState.rawValue) -> \(newState.rawValue) | \(reason)")
        }
        voiceState = newState
        voiceFeedbackSounds.play(for: newState)

    }

    private func logVoiceEvent(_ message: String) {
        if debugLoggingEnabled {
            print("voicePipeline: \(message)")
        }
    }

    private func resetVoicePerformance() {
        voicePerformanceMarks = [:]
    }

    private func markVoicePerformance(_ key: String) {
        voicePerformanceMarks[key] = Date()
    }

    private func markVoicePerformanceIfMissing(_ key: String) {
        if voicePerformanceMarks[key] == nil {
            markVoicePerformance(key)
        }
    }

    private func performanceMilliseconds(from startKey: String, to endKey: String) -> Int {
        guard let start = voicePerformanceMarks[startKey], let end = voicePerformanceMarks[endKey] else {
            return -1
        }
        return max(0, Int(end.timeIntervalSince(start) * 1000))
    }

    private func printVoicePerformanceReportIfVoiceRun() {
        guard voicePerformanceMarks["buttonPressed"] != nil else { return }

        let llmStartKey = voicePerformanceMarks["llmResponseStarted"] == nil ? "transcriptionDone" : "llmResponseStarted"
        let micReady = performanceMilliseconds(from: "buttonPressed", to: "microphoneReady")
        let recordingStart = performanceMilliseconds(from: "microphoneReady", to: "recordingStarted")
        let transcription = performanceMilliseconds(from: "recordingStopped", to: "transcriptionDone")
        let firstToken = performanceMilliseconds(from: "transcriptionDone", to: "firstLLMToken")
        let llm = performanceMilliseconds(from: llmStartKey, to: "llmResponseFinished")
        let tts = performanceMilliseconds(from: "llmResponseFinished", to: "ttsStarted")
        let playback = performanceMilliseconds(from: "ttsStarted", to: "audioPlaybackStarted")
        print(
            "VoicePerformanceReport: " +
            "micReady=\(micReady)ms, " +
            "recordingStart=\(recordingStart)ms, " +
            "transcription=\(transcription)ms, " +
            "llmFirstToken=\(firstToken)ms, " +
            "llm=\(llm)ms, " +
            "tts=\(tts)ms, " +
            "playback=\(playback)ms"
        )

        // Phase E: persist alongside the console print, not instead of it - see
        // app/core/voice_performance.py. Only non-negative numeric durations, fire-
        // and-forget so a slow/offline server never delays the voice turn itself.
        let rawMetrics: [String: Int] = [
            "micReady": micReady, "recordingStart": recordingStart, "transcription": transcription,
            "llmFirstToken": firstToken, "llm": llm, "tts": tts, "playback": playback,
        ]
        let metrics = rawMetrics.filter { $0.value >= 0 }
        if !metrics.isEmpty {
            Task { [serverController] in
                try? await serverController.recordVoicePerformance(metrics)
            }
        }
    }

    private func modelLabel(from provider: String, model: String) -> String {
        let normalized = provider.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == "openclaw" {
            return "Antwort über OpenClaw"
        }
        if normalized == "openai" {
            return "Antwort über OpenAI • \(model)"
        }
        return "Antwort über lokal • \(model)"
    }

    private func startScanPolling() {
        // Vorher fest auf 720 Iterationen a 750ms begrenzt (= 9 Minuten), dann
        // brach die Schleife bedingungslos ab - unabhaengig davon, ob noch ein
        // Scan lief. Ein Fotoindex-Scan kann (selbst mit paralleler
        // Verarbeitung) mehrere Stunden dauern, das Dashboard fror die
        // Fortschrittsanzeige also nach 9 Minuten einfach ein, obwohl der Scan
        // im Hintergrund weiterlief. Live beobachtet 2026-08-19: "die Anzeige
        // hat sich nicht richtig aktualisiert". Die stillActive-Pruefung war
        // bereits korrekt und haette selbst zuverlaessig abgebrochen, sobald
        // wirklich nichts mehr lief - die zusaetzliche feste Obergrenze war
        // unnoetig und schaedlich. Jetzt eine grosszuegige, aber nicht
        // unbegrenzte Sicherheitsgrenze (24 Stunden bei 750ms-Intervall) statt
        // 9 Minuten, damit ein haengender Task theoretisch trotzdem irgendwann
        // endet, falls stillActive aus irgendeinem Grund nie greift.
        let maxIterations = 24 * 60 * 60 * 1000 / 750
        scanPollingTask?.cancel()
        scanPollingTask = Task { [weak self] in
            for _ in 0..<maxIterations {
                if Task.isCancelled { return }
                try? await Task.sleep(for: .milliseconds(750))
                guard let self else { return }
                do {
                    try await self.refreshScanStates()
                } catch {
                    continue
                }
                let activeStatuses: Set<ScanStatus> = [.preparing, .scanning, .indexing, .downloading]
                let stillActive =
                    activeStatuses.contains(self.mailScanProgress.status) ||
                    activeStatuses.contains(self.mailBackgroundProgress.status) ||
                    activeStatuses.contains(self.photoScanProgress.status) ||
                    activeStatuses.contains(self.photoVisionProgress.status) ||
                    activeStatuses.contains(self.fileScanProgress.status)
                if !stillActive {
                    return
                }
            }
        }
    }

    private func mailScanSummary(from progress: ScanProgress) -> String {
        let folders = progress.stats["folders_found"]?.intValue ?? 0
        let mails = progress.stats["mails_found"]?.intValue ?? 0
        return "Mail-Scan fertig: \(folders) Ordner, \(mails) Mails. Ordentliches Chaos."
    }

    private func mailBackgroundSummary(from progress: ScanProgress) -> String {
        let newMails = progress.stats["new_mails"]?.intValue ?? 0
        let indexed = progress.stats["mails_indexed"]?.intValue ?? 0
        return "Mail-Hintergrundscan aktiv: \(newMails) neu, \(indexed) im Cache. Der Posteingang hat's eilig."
    }

    private func photoSummary(from progress: ScanProgress) -> String {
        let photos = progress.stats["photos_found"]?.intValue ?? 0
        let videos = progress.stats["videos_found"]?.intValue ?? 0
        let labels = progress.stats["labels_recognized"]?.intValue ?? 0
        return "Fotoindex fertig: \(photos) Fotos, \(videos) Videos, \(labels) Labels. Ganz hübsch sortiert."
    }

    private func fileSummary(from progress: ScanProgress) -> String {
        let files = progress.stats["files_found"]?.intValue ?? 0
        let folders = progress.stats["folders_found"]?.intValue ?? 0
        return "Dateiindex fertig: \(files) Dateien, \(folders) Ordner. Bürokratisch beeindruckend."
    }

    private func conversationPayload() -> [[String: String]] {
        messages
            .suffix(10)
            .compactMap { message in
                let content = message.text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !content.isEmpty else { return nil }
                switch message.role {
                case .user:
                    return ["role": "user", "content": content]
                case .jarvis:
                    return ["role": "assistant", "content": content]
                case .system:
                    return nil
                }
            }
    }
}

private final class MutableBoolBox {
    var value: Bool

    init(_ value: Bool = false) {
        self.value = value
    }
}

private final class VoiceFeedbackSoundPlayer {
    private var soundCache: [JarvisVoiceState: NSSound] = [:]
    private var lastPlayedAt: [JarvisVoiceState: Date] = [:]
    private let minimumInterval: TimeInterval = 0.45

    func play(for state: JarvisVoiceState) {
        guard feedbackSoundsEnabled else { return }

        let volume: Float
        switch state {
        case .listening:
            volume = 0.34
        case .thinking:
            volume = 0.24
        default:
            return
        }

        let now = Date()
        if let previous = lastPlayedAt[state], now.timeIntervalSince(previous) < minimumInterval {
            return
        }
        lastPlayedAt[state] = now

        guard let sound = cachedSound(for: state) else {
            NSSound.beep()
            return
        }

        sound.stop()
        sound.volume = volume
        sound.play()
    }

    private var feedbackSoundsEnabled: Bool {
        if UserDefaults.standard.object(forKey: "JarvisVoiceFeedbackSoundsEnabled") == nil {
            return true
        }
        return UserDefaults.standard.bool(forKey: "JarvisVoiceFeedbackSoundsEnabled")
    }

    private func cachedSound(for state: JarvisVoiceState) -> NSSound? {
        if let cached = soundCache[state] {
            return cached
        }

        guard let data = toneData(for: state), let sound = NSSound(data: data) else {
            return nil
        }

        soundCache[state] = sound
        return sound
    }

    private func toneData(for state: JarvisVoiceState) -> Data? {
        switch state {
        case .listening:
            return makeToneData(
                segments: [
                    ToneSegment(frequency: 659.25, duration: 0.075, amplitude: 0.40),
                    ToneSegment(frequency: 987.77, duration: 0.105, amplitude: 0.34)
                ],
                gap: 0.018
            )
        case .thinking:
            return makeToneData(
                segments: [
                    ToneSegment(frequency: 523.25, duration: 0.060, amplitude: 0.22),
                    ToneSegment(frequency: 783.99, duration: 0.070, amplitude: 0.18),
                    ToneSegment(frequency: 659.25, duration: 0.090, amplitude: 0.15)
                ],
                gap: 0.012
            )
        default:
            return nil
        }
    }

    private func makeToneData(segments: [ToneSegment], gap: Double) -> Data {
        let sampleRate = 44_100
        var samples: [Int16] = []

        for (index, segment) in segments.enumerated() {
            samples.append(contentsOf: makeToneSamples(segment: segment, sampleRate: sampleRate))
            if index < segments.count - 1 {
                samples.append(contentsOf: Array(repeating: 0, count: Int(Double(sampleRate) * gap)))
            }
        }

        return makeWavData(samples: samples, sampleRate: sampleRate)
    }

    private func makeToneSamples(segment: ToneSegment, sampleRate: Int) -> [Int16] {
        let count = max(1, Int(segment.duration * Double(sampleRate)))
        let twoPi = Double.pi * 2.0

        return (0..<count).map { sampleIndex in
            let progress = Double(sampleIndex) / Double(max(1, count - 1))
            let attack = min(1.0, progress / 0.16)
            let release = min(1.0, (1.0 - progress) / 0.32)
            let envelope = max(0.0, min(attack, release))
            let shimmer = 0.72 * sin(twoPi * segment.frequency * Double(sampleIndex) / Double(sampleRate))
                + 0.18 * sin(twoPi * segment.frequency * 2.0 * Double(sampleIndex) / Double(sampleRate))
            let value = shimmer * envelope * segment.amplitude
            return Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))
        }
    }

    private func makeWavData(samples: [Int16], sampleRate: Int) -> Data {
        var data = Data()
        let byteRate = UInt32(sampleRate * 2)
        let blockAlign = UInt16(2)
        let bitsPerSample = UInt16(16)
        let subchunk2Size = UInt32(samples.count * 2)
        let chunkSize = UInt32(36) + subchunk2Size

        data.appendAscii("RIFF")
        data.appendLittleEndian(chunkSize)
        data.appendAscii("WAVE")
        data.appendAscii("fmt ")
        data.appendLittleEndian(UInt32(16))
        data.appendLittleEndian(UInt16(1))
        data.appendLittleEndian(UInt16(1))
        data.appendLittleEndian(UInt32(sampleRate))
        data.appendLittleEndian(byteRate)
        data.appendLittleEndian(blockAlign)
        data.appendLittleEndian(bitsPerSample)
        data.appendAscii("data")
        data.appendLittleEndian(subchunk2Size)

        for sample in samples {
            data.appendLittleEndian(UInt16(bitPattern: sample))
        }

        return data
    }
}

private struct ToneSegment {
    let frequency: Double
    let duration: Double
    let amplitude: Double
}

private extension Data {
    mutating func appendAscii(_ string: String) {
        append(contentsOf: string.utf8)
    }

    mutating func appendLittleEndian<T: FixedWidthInteger>(_ value: T) {
        var littleEndianValue = value.littleEndian
        Swift.withUnsafeBytes(of: &littleEndianValue) { bytes in
            append(contentsOf: bytes)
        }
    }
}
