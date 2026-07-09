import AppKit
import AVFoundation
import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    @Published var selectedSection: JarvisSection = .home
    @Published var status: JarvisRuntimeStatus = .offline
    @Published var voiceState: JarvisVoiceState = .idle
    @Published var messages: [ChatMessage] = [
        ChatMessage(role: .system, text: "Jarvis App bereit. Ich starte den lokalen Core automatisch. Sehr höflich von mir, finde ich.")
    ]
    @Published var modelStatus = ModelStatus()
    @Published var privacySummary = "Datenschutzstatus wird geladen ..."
    @Published var permissions: [String: PermissionInfo] = [:]
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
    @Published var dailyBriefingText = "Noch kein Tagesbriefing geladen."
    @Published var lastAnswerSource = "lokal"
    @Published var composerDraft = ""
    @Published var onboardingCompleted = UserDefaults.standard.bool(forKey: "JarvisOnboardingCompleted")
    @Published var language = UserDefaults.standard.string(forKey: "JarvisLanguage") ?? "Deutsch"
    @Published var userName = UserDefaults.standard.string(forKey: "JarvisUserName") ?? "Leon"
    @Published var userSalutation = UserDefaults.standard.string(forKey: "JarvisUserSalutation") ?? "sir"
    @Published var fastVoiceMode = UserDefaults.standard.object(forKey: "JarvisFastVoiceMode") as? Bool ?? true
    @Published var lastError: String?

    let serverController = LocalServerController()

    private lazy var ttsService = EdgeTTSService(controller: serverController)
    private lazy var audioCaptureService = AudioCaptureService()
    private var reconnectTask: Task<Void, Never>?
    private var scanPollingTask: Task<Void, Never>?
    private var isBootstrapping = false
    private var isVoiceRequestRunning = false
    private var didSpeakStartupGreeting = false
    private var keepListeningAfterGreeting = false
    @Published private(set) var autoListenEnabled = true
    private var isJarvisSpeaking = false
    private var voicePerformanceMarks: [String: Date] = [:]
    private let voiceFeedbackSounds = VoiceFeedbackSoundPlayer()
    private var microphoneWarmupTask: Task<Bool, Never>?
    private var nextVoiceListenTask: Task<Void, Never>?
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
            await saveUserProfileToCore()
            await saveFastVoiceModeToCore()
        }
        autoListenEnabled = true
        keepListeningAfterGreeting = true
        await presentStartupGreetingIfNeeded()
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

    func saveUserProfileToCore() async {
        saveUserProfileLocally()
        do {
            try await serverController.setUserProfile(userName: displayUserName, salutation: userSalutation)
        } catch {
            lastError = "Profil wurde lokal gespeichert. Der Core übernimmt es beim nächsten erfolgreichen Start."
        }
    }

    func saveFastVoiceModeToCore() async {
        UserDefaults.standard.set(fastVoiceMode, forKey: "JarvisFastVoiceMode")
        do {
            try await serverController.setFastVoiceMode(fastVoiceMode)
        } catch {
            lastError = "Schneller Sprachmodus wurde lokal gespeichert. Der Core übernimmt ihn beim nächsten erfolgreichen Start."
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

    func ensureServerConnected() async {
        guard !isBootstrapping else { return }
        isBootstrapping = true
        defer { isBootstrapping = false }

        if await refreshStatus(startIfOffline: false) { return }

        status = .offline
        lastError = "Ich starte den lokalen Core ..."
        _ = serverController.start()

        for _ in 0..<16 {
            try? await Task.sleep(for: .milliseconds(200))
            if await refreshStatus(startIfOffline: false) {
                lastError = nil
                return
            }
        }

        status = .offline
        serverController.captureLaunchFailureDetail()
        lastError = serverController.lastLaunchError ?? "Der lokale Core konnte nicht automatisch starten."
    }

    @discardableResult
    func refreshStatus(startIfOffline: Bool = true, includeScanStates: Bool = false) async -> Bool {
        do {
            let health = try await serverController.health()
            status = health.ok ? .idle : .offline
            modelStatus = try await serverController.models()
            privacySummary = try await serverController.privacyStatus()
            permissions = try await serverController.permissions()
            if includeScanStates {
                try? await refreshScanStates()
            }
            lastError = nil
            return health.ok
        } catch {
            status = .offline
            modelStatus = ModelStatus()
            privacySummary = "Datenschutzstatus wird geladen ..."
            permissions = [:]
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
            let streamed = try await serverController.chatStream(trimmed, history: history) { [weak self] chunk in
                guard let self else { return }
                self.messages[answerIndex].text.append(chunk)
            }
            if messages[answerIndex].text.isEmpty {
                messages[answerIndex].text = streamed
            }
            let response = ChatResponse(
                answer: messages[answerIndex].text,
                source: modelStatus.provider,
                model: modelStatus.activeModel
            )
            lastAnswerSource = modelLabel(from: response.source ?? modelStatus.provider, model: response.model ?? modelStatus.activeModel)
            keepListeningAfterGreeting = true
            await speakAnswer(response.answer)
            status = .idle
        } catch {
            let detail = serverController.lastLaunchError.map { " Technisch: \($0)" } ?? ""
            messages[answerIndex].text = "Ich erreiche den lokalen Core gerade nicht. Ich verbinde im Hintergrund neu.\(detail)"
            status = .offline
            setVoiceState(.error, reason: "text_message_failed")
            await ensureServerConnected()
        }
    }

    func listenOnce() async {
        await listenOnce(retryCount: 0, allowWhileSpeaking: false)
    }

    private func listenOnce(retryCount: Int, allowWhileSpeaking: Bool) async {
        guard !isVoiceRequestRunning else { return }
        isVoiceRequestRunning = true
        defer { isVoiceRequestRunning = false }

        if retryCount == 0 && !allowWhileSpeaking {
            voiceStopGeneration += 1
            resumeContinuousVoiceMode(reason: "manual_voice_start")
        } else if allowWhileSpeaking {
            guard autoListenEnabled, keepListeningAfterGreeting else { return }
        }

        if !allowWhileSpeaking {
            await stopCurrentSpeech()
            await serverController.setVoiceSpeakingState(false)
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
            return
        }

        markVoicePerformance("microphoneReady")
        setVoiceState(.listening, reason: "microphone_ready")
        if status == .offline {
            await ensureServerConnected()
        }

        let voiceTranscript: VoiceTranscriptionResponse
        let recordingMarker = MutableBoolBox()
        do {
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
            voiceTranscript = try await serverController.transcribeVoice(audioPath: capture.fileURL.path, sampleRate: capture.sampleRate)
            if let error = voiceTranscript.error?.trimmingCharacters(in: .whitespacesAndNewlines), !error.isEmpty {
                throw NSError(domain: "JarvisVoiceTranscription", code: -1, userInfo: [NSLocalizedDescriptionKey: error])
            }
        } catch {
            let detail = error.localizedDescription
            if let captureError = error as? AudioCaptureService.CaptureError {
                switch captureError {
                case .noSpeechDetected, .cancelled:
                    status = .idle
                    setVoiceState(.idle, reason: "listen_no_speech")
                    return
                case .permissionDenied:
                    status = .offline
                    setVoiceState(.error, reason: "microphone_permission_denied")
                    messages.append(ChatMessage(role: .system, text: "Die Sprachaufnahme konnte nicht starten. Technisch: \(detail)"))
                    return
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
                await listenOnce(retryCount: 1, allowWhileSpeaking: false)
                return
            }
            setVoiceState(.idle, reason: "error_reset")
            await ensureServerConnected()
            return
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
            return
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
        guard let answerIndex = messages.firstIndex(where: { $0.id == jarvisMessage.id }) else { return }

        do {
            status = .responding
            markVoicePerformance("llmResponseStarted")
            let streamed = try await serverController.chatStream(finalUserText.isEmpty ? finalTranscript : finalUserText, history: history) { [weak self] chunk in
                guard let self else { return }
                self.messages[answerIndex].text.append(chunk)
                if self.voiceState != .jarvisSpeaking {
                    self.setVoiceState(.thinking, reason: "assistant_streaming")
                }
            }
            markVoicePerformance("llmResponseFinished")
            if messages[answerIndex].text.isEmpty {
                messages[answerIndex].text = streamed
            }
            let response = ChatResponse(
                answer: messages[answerIndex].text,
                source: modelStatus.provider,
                model: modelStatus.activeModel
            )
            lastAnswerSource = modelLabel(from: response.source ?? modelStatus.provider, model: response.model ?? modelStatus.activeModel)
            keepListeningAfterGreeting = true
            if shouldStopAfterThisTurn {
                pauseContinuousVoiceMode(reason: "stop_phrase_detected")
            } else {
                resumeContinuousVoiceMode(reason: "continue_after_voice_response")
            }
            await speakAnswer(response.answer)
        } catch {
            let detail = serverController.lastLaunchError.map { " Technisch: \($0)" } ?? ""
            messages[answerIndex].text = "Ich erreiche den lokalen Core gerade nicht. Ich verbinde im Hintergrund neu.\(detail)"
            status = .offline
            setVoiceState(.error, reason: "listen_failed")
            await ensureServerConnected()
        }

        status = .idle
        setVoiceState(.idle, reason: "listen_finished")
    }

    func switchModel(provider: String? = nil, model: String? = nil) async {
        await ensureServerConnected()
        status = .thinking
        do {
            modelStatus = try await serverController.setModel(provider: provider, model: model)
            status = .idle
        } catch {
            status = .offline
            lastError = "Modellwechsel fehlgeschlagen. Ich verbinde neu."
            await ensureServerConnected()
        }
    }



    func performMailCommand(_ command: String) async {
        await stopCurrentSpeech()
        await ensureServerConnected()
        let history = conversationPayload()
        mailIsLoading = true
        status = .thinking
        setVoiceState(.thinking, reason: "mail_command_started")
        defer { mailIsLoading = false }

        do {
            let response = try await serverController.chat(command, history: history)
            mailResult = response.answer
            messages.append(ChatMessage(role: .user, text: command))
            messages.append(ChatMessage(role: .jarvis, text: response.answer))
            lastAnswerSource = modelLabel(from: response.source ?? modelStatus.provider, model: response.model ?? modelStatus.activeModel)
            keepListeningAfterGreeting = true
            await speakAnswer(response.answer)
            status = .idle
            await refreshStatus(startIfOffline: false)
        } catch {
            mailResult = "Mail-Aktion fehlgeschlagen. Jarvis zieht kurz die Augenbraue hoch."
            status = .offline
            setVoiceState(.error, reason: "mail_command_failed")
            await ensureServerConnected()
        }
    }

    func refreshScanStates() async throws {
        let bundle = try await serverController.scanStatus()
        mailScanProgress = bundle.mailScan
        mailBackgroundProgress = bundle.mailBackground
        photoScanProgress = bundle.photos
        photoVisionProgress = bundle.photoVision
        fileScanProgress = bundle.files
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
        await ensureServerConnected()
        mailIsLoading = true
        mailScanProgress.status = .preparing
        mailScanProgress.currentLabel = "Mail-Scan wird vorbereitet."
        defer { mailIsLoading = false }
        do {
            mailScanProgress = try await serverController.startMailFolderScan()
            startScanPolling()
            mailResult = mailScanSummary(from: mailScanProgress)
        } catch {
            mailScanProgress.status = .failed
            mailScanProgress.errorMessage = error.localizedDescription
            mailResult = "Mail-Scan fehlgeschlagen. Die Ordner waren heute eigenwillig."
        }
    }

    func startMailBackgroundScan() async {
        await ensureServerConnected()
        mailIsLoading = true
        mailBackgroundProgress.status = .scanning
        mailBackgroundProgress.currentLabel = "Mail-Hintergrundscan startet."
        defer { mailIsLoading = false }
        do {
            mailBackgroundProgress = try await serverController.startMailBackgroundScan()
            startScanPolling()
            mailResult = mailBackgroundSummary(from: mailBackgroundProgress)
        } catch {
            mailBackgroundProgress.status = .failed
            mailBackgroundProgress.errorMessage = error.localizedDescription
            mailResult = "Mail-Hintergrundscan fehlgeschlagen. Der Posteingang spielt Theater."
        }
    }

    func refreshPhotoPermissionStatus() async {
        await ensureServerConnected()
        do {
            photoPermissionStatus = try await serverController.photoPermissionStatus()
            localVisionStatus = try await serverController.localPhotoVisionStatus()
        } catch {
            photoPermissionStatus = "nicht lesbar"
        }
    }

    func requestPhotoPermission() async {
        await ensureServerConnected()
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoResult = try await serverController.requestPhotoPermission()
            await refreshPhotoPermissionStatus()
            try? await refreshScanStates()
        } catch {
            photoResult = "Fotos-Freigabe fehlgeschlagen. Apple hatte wieder eigene Ideen."
        }
    }

    func startPhotoIndexScan() async {
        await ensureServerConnected()
        photoIsLoading = true
        photoScanProgress.status = .preparing
        photoScanProgress.currentLabel = "Fotoindex wird vorbereitet."
        defer { photoIsLoading = false }
        do {
            photoScanProgress = try await serverController.startPhotoIndexScan()
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
        await ensureServerConnected()
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoScanProgress = try await serverController.resetPhotoIndex()
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
            lastAnswerSource = modelLabel(from: response.source ?? modelStatus.provider, model: response.model ?? modelStatus.activeModel)
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
        await ensureServerConnected()
        do {
            localVisionStatus = try await serverController.localPhotoVisionStatus()
            photoResult = localVisionStatus.message
        } catch {
            photoResult = "Vision-Modell nicht geprüft. Keine Lust auf Raterei."
        }
    }

    func refreshCalendarOverview() async {
        await ensureServerConnected()
        do {
            calendarOverview = try await serverController.calendarOverview()
        } catch {
            lastError = "Kalenderübersicht konnte nicht geladen werden."
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
        await ensureServerConnected()
        photoIsLoading = true
        photoVisionProgress.status = .preparing
        photoVisionProgress.currentLabel = "Lokale Fotoanalyse wird vorbereitet."
        defer { photoIsLoading = false }
        do {
            localVisionStatus = try await serverController.localPhotoVisionStatus()
            photoVisionProgress = try await serverController.startLocalPhotoVisionAnalysis()
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
        await ensureServerConnected()
        photoIsLoading = true
        defer { photoIsLoading = false }
        do {
            photoVisionProgress = try await serverController.resetLocalPhotoVisionDescriptions()
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
            lastAnswerSource = modelLabel(from: response.source ?? modelStatus.provider, model: response.model ?? modelStatus.activeModel)
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
        await ensureServerConnected()
        fileIsLoading = true
        fileScanProgress.status = .preparing
        fileScanProgress.currentLabel = "Dateiindex wird vorbereitet."
        defer { fileIsLoading = false }
        do {
            fileScanProgress = try await serverController.startFileIndexScan()
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
        await ensureServerConnected()
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            let payload = try await serverController.searchFiles(query: cleanQuery)
            lastFileSearchQuery = payload.query
            fileSearchText = payload.query
            fileSearchResults = payload.results
            fileResult = payload.message
            await refreshScanStatesSafely()
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
        await ensureServerConnected()
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            let message = try await serverController.moveFileSearchResults(query: cleanQuery, targetFolder: cleanTarget)
            fileResult = message
            await searchFilesInIndex(cleanQuery)
            await refreshScanStatesSafely()
        } catch {
            fileResult = "Dateien konnten nicht verschoben werden. Sie wollten wohl bleiben."
        }
    }

    func resetFileIndex() async {
        await ensureServerConnected()
        fileIsLoading = true
        defer { fileIsLoading = false }
        do {
            fileScanProgress = try await serverController.resetFileIndex()
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
            await serverController.setVoiceSpeakingState(true)
            try await ttsService.speak(greeting) { [weak self] event in
                guard let self else { return }
                switch event {
                case .ttsStarted:
                    self.markVoicePerformance("ttsStarted")
                    self.scheduleNextVoiceListen()
                case .audioPlaybackStarted:
                    self.markVoicePerformance("audioPlaybackStarted")
                case .ttsFinished:
                    self.markVoicePerformance("ttsFinished")
                default:
                    break
                }
            }
            isJarvisSpeaking = false
            await serverController.setVoiceSpeakingState(false)
            setVoiceState(.idle, reason: "startup_greeting_finished")
            didSpeakStartupGreeting = true
            keepListeningAfterGreeting = true
            scheduleNextVoiceListen()
        } catch {
            isJarvisSpeaking = false
            await serverController.setVoiceSpeakingState(false)
            let detail = error.localizedDescription
            logVoiceEvent("startup greeting failed: \(detail)")
            lastError = "Die Begrüßung konnte noch nicht abgespielt werden."
            setVoiceState(.error, reason: "startup_greeting_failed")
        }
    }

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

        let endings = [
            "\(userAddress). Wie kann ich helfen?",
            "\(userAddress). Ich bin bereit, wenn Sie es sind.",
            "\(userAddress). Womit starten wir?",
            "\(userAddress). Ich höre zu. Sogar freiwillig."
        ]
        let ending = endings.randomElement() ?? "\(userAddress). Wie kann ich helfen?"
        return "\(baseGreeting), \(ending)"
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
        await serverController.setVoiceSpeakingState(false)
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
            await serverController.setVoiceSpeakingState(true)
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
            await serverController.setVoiceSpeakingState(false)
            if voiceState == .jarvisSpeaking {
                logVoiceEvent("tts finished timestamp=\(Date())")
                setVoiceState(.idle, reason: "tts_finished")
            }
            printVoicePerformanceReportIfVoiceRun()
            scheduleNextVoiceListen()
        } catch {
            isJarvisSpeaking = false
            await serverController.setVoiceSpeakingState(false)
            setVoiceState(.error, reason: "tts_failed")
            lastError = "Sprachausgabe konnte nicht abgespielt werden."
            printVoicePerformanceReportIfVoiceRun()
            if voiceState == .error {
                setVoiceState(.idle, reason: "tts_error_reset")
            }
        }
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
    }

    private func modelLabel(from provider: String, model: String) -> String {
        let normalized = provider.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == "openai" {
            return "Antwort über OpenAI • \(model)"
        }
        return "Antwort über lokal • \(model)"
    }

    private func startReconnectLoop() {
        guard reconnectTask == nil else { return }
        reconnectTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                guard let self else { return }
                guard self.status == .offline else { continue }
                await self.refreshStatus(startIfOffline: true)
            }
        }
    }

    private func startScanPolling() {
        scanPollingTask?.cancel()
        scanPollingTask = Task { [weak self] in
            for _ in 0..<720 {
                if Task.isCancelled { return }
                try? await Task.sleep(for: .milliseconds(750))
                guard let self else { return }
                do {
                    try await self.refreshScanStates()
                } catch {
                    continue
                }
                let activeStatuses: Set<ScanStatus> = [.preparing, .scanning, .indexing]
                let stillActive =
                    activeStatuses.contains(self.mailScanProgress.status) ||
                    activeStatuses.contains(self.mailBackgroundProgress.status) ||
                    activeStatuses.contains(self.photoScanProgress.status) ||
                    activeStatuses.contains(self.photoVisionProgress.status) ||
                    activeStatuses.contains(self.fileScanProgress.status)
                if !stillActive { return }
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
