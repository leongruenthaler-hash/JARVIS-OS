import Foundation
import Speech
import AVFoundation

/// Voice input/output for JarvisMobile. Three listening modes share the same
/// AVAudioEngine/SFSpeechRecognizer plumbing:
/// - Manual (mic button, ChatView): user taps to start/stop, text lands in
///   the editable draft field, NEVER auto-sends (see ChatView's request to
///   let the user review/edit before committing, 2026-09-07).
/// - Wake-word: continuous background listening for "Jarvis" (+ fuzzy
///   aliases). SFSpeechRecognizer caps a single request at ~1 minute, so this
///   chains fresh recognition segments back-to-back on the SAME running
///   audio tap to approximate "always on" without a real gap.
/// - Follow-up: after Jarvis finishes speaking, listens again WITHOUT
///   requiring the wake word again (mirrors the old Mac Jarvis conversation
///   flow, live requested 2026-09-07) - a pause in speech auto-sends what was
///   said, unless it matches an end-of-conversation phrase ("danke jarvis",
///   "das passt" etc.), in which case it silently drops back to wake-word-only
///   listening instead.
@MainActor
final class VoiceManager: NSObject, ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var isSpeaking = false
    @Published private(set) var isWakeListening = false
    /// True specifically once the wake word fired or a follow-up capture
    /// started - distinguishes "capturing a command, auto-send on silence"
    /// from "still just watching for the wake word". Published so ChatView
    /// can tell the two apart: `liveTranscript` is also used internally as
    /// scratch space while just watching for the wake word, and must NOT
    /// leak into the visible draft field during that phase (live-reported
    /// bug 2026-09-08: the input field flickered on/off constantly because
    /// it mirrored `liveTranscript` unconditionally, including ambient noise
    /// picked up before "Jarvis" was even said).
    @Published private(set) var isCapturingCommand = false
    @Published private(set) var liveTranscript = ""
    @Published var errorMessage: String?
    /// Set once a wake-triggered or follow-up capture has a full utterance
    /// (user paused) - ChatView observes this, sends it as a chat message,
    /// then clears it back to nil. Kept separate from `liveTranscript` (which
    /// the manual mic button also drives) so the two flows never interfere.
    @Published private(set) var pendingWakeCommand: String?
    /// Set when a captured utterance matched an end-of-conversation phrase
    /// ("danke jarvis, das passt soweit" etc.) - ChatView shows/speaks this
    /// as Jarvis's own closing reply (mirroring the fixed farewell response
    /// in the old JARVIS-OS backend, app/jarvis.py::is_end_command()), then
    /// resumes pure wake-word-only listening instead of another follow-up
    /// capture.
    @Published private(set) var pendingFarewell: String?

    /// UserDefaults key backing ChatView's speaker toggle, so it survives app restarts.
    static let speakRepliesKey = "JarvisSpeakRepliesAloud"
    /// UserDefaults key for SettingsView's "Aktivierungswort" toggle.
    static let wakeListeningEnabledKey = "JarvisWakeListeningEnabled"

    // Gleiche Fuzzy-Aktivierungswort-Liste wie config.json::wake_words auf dem
    // Mac Mini/der alten JarvisApp - deckt haeufige Fehlerkennungen von
    // "Jarvis" durch die Spracherkennung ab.
    private static let wakeWordAliases: Set<String> = [
        "jarvis", "javis", "jarves", "jarvice", "jarvies", "jarvisse",
        "jathers", "jaros", "jarus", "trabbers", "jobs", "john", "thomas",
        "travis", "charvis", "jarwes", "jarviss",
    ]

    // 1:1 portiert aus app/jarvis.py::END_PHRASES + is_end_command() (altes
    // JARVIS-OS-Backend) statt der urspruenglichen simplen Substring-Liste -
    // die alte Swift-Version erkannte z.B. "Okay, das passt soweit" oder
    // "Ok, danke, das passt" nicht zuverlässig, weil sie nur ein paar feste
    // Saetze als Ganzes kannte. Das Python-Original deckt genau diese
    // Variationen bereits robust ab (live gemeldeter Bug 2026-09-08: "das mit
    // dem Satz, dass Jarvis in den Aktivierungswort-Modus zurueckgeht,
    // funktioniert noch nicht so zuverlaessig").
    private static let endPhrases: Set<String> = [
        "danke jarvis das passt", "danke jarvis das passt soweit",
        "danke das passt", "danke das passt soweit",
        "nein danke das passt", "nein danke das passt soweit",
        "das passt", "das passt soweit", "passt soweit",
        "bis später", "bis spaeter", "tschüss", "tschuess",
        "beenden", "stop",
    ]

    private static let endPhrasePatterns: [NSRegularExpression] = [
        "^(?:okay|ok|alles klar)?\\s*(?:danke|dank dir)?\\s*(?:das )?passt(?: soweit)?$",
        "^(?:danke|dank dir)\\s*(?:das )?passt(?: soweit)?$",
        "^(?:nein )?danke\\s*(?:das )?passt(?: soweit)?$",
        "^(?:alles klar|okay|ok)\\s*(?:das )?passt(?: soweit)?$",
        "^(?:bis später|bis spaeter|tschüss|tschuess)$",
    ].compactMap { try? NSRegularExpression(pattern: $0, options: [.caseInsensitive]) }

    // Entspricht Python's normalize_text(): klein schreiben, Bindestriche zu
    // Leerzeichen, Satzzeichen weg, Mehrfach-Leerzeichen zusammenfassen.
    private static func normalize(_ text: String) -> String {
        var normalized = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        normalized = normalized.replacingOccurrences(of: "-", with: " ")
        normalized = normalized.replacingOccurrences(of: "[,;:]+", with: " ", options: .regularExpression)
        normalized = normalized.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        return normalized.trimmingCharacters(in: CharacterSet(charactersIn: " ,.!?;:"))
    }

    // Nur die unverwechselbaren Mehrwort-Kernphrasen, NICHT Einzelwoerter wie
    // "stop"/"beenden" - die wuerden sonst schon als Substring in ganz anderen
    // Woertern falsch anschlagen (z.B. "stoppen" enthaelt "stop").
    private static let endCoreMarkers = [
        "das passt soweit", "das passt", "passt soweit",
        "bis später", "bis spaeter", "tschüss", "tschuess",
    ]

    private static func isEndCommand(_ text: String) -> Bool {
        let normalized = normalize(text)
        if endPhrases.contains(normalized) { return true }
        let range = NSRange(normalized.startIndex..., in: normalized)
        if endPhrasePatterns.contains(where: { $0.firstMatch(in: normalized, options: [], range: range) != nil }) {
            return true
        }
        // Die exakten/verankerten Muster oben (1:1 aus app/jarvis.py) verlangen
        // eine komplette Uebereinstimmung des GESAMTEN Satzes - echte, frei
        // gesprochene Abschluss-Saetze haben aber oft zusaetzliche
        // Fuellwoerter ("Perfekt, danke dir Jarvis, das passt soweit"), die
        // daran vorbeirutschen. Als Rueckfallebene reicht es, wenn eine der
        // unverwechselbaren Kernphrasen IRGENDWO im Satz vorkommt (live
        // gemeldeter Bug 2026-09-08: ein "korrekt ausgesprochener"
        // Abschlusssatz mit solchen Fuellwoertern wurde trotzdem nicht als
        // Ende des Gespraechs erkannt).
        return Self.endCoreMarkers.contains { normalized.contains($0) }
    }

    // Entspricht der festen Antwort in app/jarvis.py bei is_end_command():
    // "Alles klar. Ich bin wieder still, bis Sie Jarvis sagen." - hier auf
    // die informelle "du"-Anrede angepasst, die dieser Agent (siehe
    // OpenClaw-Antworten wie "Und bei dir?") bereits durchgehend nutzt.
    private static let farewellReply = "Alles klar, sir. Ich bin still, bis du wieder \"Jarvis\" sagst."

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "de-DE"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let synthesizer = AVSpeechSynthesizer()
    /// True while the CURRENT recognition segment is either wake-listening
    /// (watching only for the wake word) or auto-send capture (watching for
    /// a pause to finish an utterance) - false for a manual mic-button press.
    private var isAutomaticSegment = false
    private var silenceTimer: Timer?
    /// Incremented every time a fresh recognition segment/task starts;
    /// captured by that segment's completion closure so a callback from an
    /// ABANDONED segment (e.g. the wake-listening request we just replaced
    /// with a fresh command-capture request) can be told apart from the
    /// current one and ignored, instead of resurrecting stale state.
    private var segmentGeneration = 0
    /// Resolved when speech genuinely finishes (or is cancelled) - lets
    /// callers `await` real completion instead of just dispatch, so a
    /// caller-held UIBackgroundTask (see ChatView.send()) can stay alive
    /// through the ENTIRE utterance instead of ending the moment
    /// synthesizer.speak() returns (which happens near-instantly, long
    /// before audio actually finishes) - live bug 2026-09-07: backgrounded
    /// replies never started speaking because the background-task grace
    /// period had already elapsed by the time audio was ready to play.
    private var speakContinuation: CheckedContinuation<Void, Never>?
    /// Same completion-await pattern as `speakContinuation`, but for the
    /// Edge-TTS playback path (AVAudioPlayer instead of AVSpeechSynthesizer -
    /// they're mutually exclusive per speak() call, never both in flight).
    private var edgeAudioPlayer: AVAudioPlayer?
    private var edgePlaybackContinuation: CheckedContinuation<Void, Never>?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func requestPermissions() async -> Bool {
        let speechStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
        guard speechStatus == .authorized else { return false }
        return await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    /// Starts live, on-device transcription for a MANUAL mic-button press -
    /// `liveTranscript` updates as the user speaks, mirroring ChatGPT's
    /// voice-input UX. Never auto-sends; the caller (ChatView) decides when
    /// to stop and what to do with the result.
    func startListening() throws {
        guard !isListening, !isWakeListening else { return }
        isAutomaticSegment = false
        isCapturingCommand = false
        try beginRecognitionSegment(resetTranscript: true)
    }

    /// Stops capture; `liveTranscript` keeps whatever was recognized so the
    /// caller can send it (recognition itself may finish a beat later).
    func stopListening() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        teardownAudioEngine()
    }

    /// Begins continuous wake-word-only listening - chains fresh recognition
    /// segments back-to-back (see class doc) so it keeps running past
    /// SFSpeechRecognizer's ~1-minute cap without a real gap in coverage.
    func startWakeListening() {
        guard !isWakeListening, !isListening, !isSpeaking else { return }
        isWakeListening = true
        beginWakeSegment()
    }

    func stopWakeListening() {
        guard isWakeListening else { return }
        isWakeListening = false
        silenceTimer?.invalidate()
        silenceTimer = nil
        teardownAudioEngine()
    }

    /// Starts capturing a command WITHOUT requiring the wake word again -
    /// called right after Jarvis finishes speaking, so a follow-up ("und was
    /// ist mit morgen?") doesn't need "Jarvis" repeated (live requested
    /// 2026-09-07). Falls back to wake-word-only listening if the user stays
    /// silent or says an end-of-conversation phrase - see
    /// evaluateCapturedCommand().
    func startFollowUpListening() async {
        guard !isListening, !isSpeaking else { return }
        // Kurze Verschnaufpause, bevor die Aufnahme-Session aktiviert wird -
        // unmittelbar nach synthesizer.speak()'s didFinish braucht das
        // Audio-Hardware-Routing noch einen Moment, um die Wiedergabe-Route
        // wirklich freizugeben. Startet man die Aufnahme-Session zu schnell
        // danach, liefert der Mic-Tap leere/ungueltige Puffer, ohne dass
        // irgendwo ein Fehler auftritt - der Erkenner bekommt schlicht nie
        // Audio und liefert nie ein Ergebnis (live gemeldeter Bug 2026-09-08:
        // Mikro zeigte "Ich höre zu...", aber nichts wurde je transkribiert).
        try? await Task.sleep(nanoseconds: 200_000_000)
        guard !isListening, !isSpeaking else { return }
        isAutomaticSegment = true
        isCapturingCommand = true
        try? beginRecognitionSegment(resetTranscript: true)
        resetSilenceTimer(initial: true)
    }

    /// True once the audio session/engine/tap are physically up and running -
    /// tracked separately from `isListening` (which also flips false for a
    /// beat during an internal wake-segment re-chain, see
    /// `handleRecognitionUpdate`) so re-chaining never redoes the expensive
    /// session/tap setup while the mic is still actually running.
    private var isAudioEngineActive = false
    /// Guards against a fast error/isFinal loop restarting the recognizer
    /// dozens of times per second - each restart used to redo
    /// AVAudioSession.setCategory/setActive, which is expensive enough to
    /// visibly stutter the UI and glitch the mic (live-reported bug
    /// 2026-09-08: "mega langsam und ruckeln" while wake-listening, and the
    /// wake word never actually got recognized because segments kept getting
    /// cut off before "Jarvis" finished).
    private var isRestartScheduled = false

    private func beginWakeSegment() {
        guard isWakeListening, !isListening else { return }
        isAutomaticSegment = true
        isCapturingCommand = false
        try? beginRecognitionSegment(resetTranscript: true)
    }

    /// Schedules a wake-segment restart after a short delay instead of
    /// recursing immediately - without this, a recognizer that keeps ending
    /// segments quickly (e.g. no speech detected in a quiet room) restarts in
    /// a tight loop, each iteration re-touching the audio session. The delay
    /// is imperceptible for a real gap in speech but stops the runaway loop.
    private func scheduleWakeSegmentRestart() {
        guard !isRestartScheduled else { return }
        isRestartScheduled = true
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 300_000_000)
            self.isRestartScheduled = false
            self.beginWakeSegment()
        }
    }

    private func beginRecognitionSegment(resetTranscript: Bool) throws {
        guard let recognizer, recognizer.isAvailable else {
            throw VoiceError.recognizerUnavailable
        }
        stopSpeaking()
        if resetTranscript { liveTranscript = "" }
        errorMessage = nil

        // Session/Tap/Engine nur EINMAL pro Zuhoer-Lauf aufsetzen - das ist
        // der teure Teil (Audio-HAL-Rekonfiguration, kann hoerbar/spuerbar
        // ruckeln). Ein interner Segment-Wechsel (1-Minuten-Limit oder ein
        // frueher Abbruch bei Stille) tauscht danach nur noch die leichte
        // Request/Task-Instanz aus, siehe Tap-Closure unten, die dynamisch
        // ueber `self.recognitionRequest` statt eine fest eingefangene lokale
        // Variable anspricht.
        if !isAudioEngineActive {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let inputNode = audioEngine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                self?.recognitionRequest?.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isAudioEngineActive = true
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = true
        // .dictation signals long-form, open-ended speech - without this the
        // recognizer's default endpointing treats a ~1s pause as the end of
        // an utterance and fires `isFinal` almost immediately in a quiet
        // room, which is what was causing the restart storm above.
        request.taskHint = .dictation
        recognitionRequest = request
        isListening = true

        segmentGeneration += 1
        let generation = segmentGeneration
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                guard generation == self.segmentGeneration else { return }
                self.handleRecognitionUpdate(result: result, error: error)
            }
        }
    }

    private func handleRecognitionUpdate(result: SFSpeechRecognitionResult?, error: Error?) {
        if let result {
            liveTranscript = result.bestTranscription.formattedString
            if isAutomaticSegment {
                if !isCapturingCommand {
                    // Noch im reinen Aktivierungswort-Modus - Text auf Treffer pruefen.
                    let lower = liveTranscript.lowercased()
                    if Self.wakeWordAliases.contains(where: { lower.contains($0) }) {
                        beginCommandCaptureSegment()
                        return
                    }
                } else {
                    resetSilenceTimer()
                }
            }
        }
        if error != nil || result?.isFinal == true {
            // Segment durch SFSpeechRecognizer selbst beendet (~1-Minuten-Limit
            // erreicht) - bei automatischen Modi sofort ein frisches Segment
            // anschliessen, damit effektiv keine Zuhoer-Luecke entsteht.
            if isWakeListening && isAutomaticSegment {
                recognitionTask = nil
                recognitionRequest = nil
                isListening = false
                if isCapturingCommand {
                    // Command-Erfassung lief gerade, als das Segment endete -
                    // das Bisherige noch auswerten, statt es zu verwerfen.
                    evaluateCapturedCommand()
                } else {
                    // Reines Aktivierungswort-Zuhoeren, noch nichts erkannt -
                    // ueber den Debounce neu starten statt direkt, damit ein
                    // Erkenner, der bei Stille schnell abbricht, nicht in eine
                    // Neustart-Schleife mit staendiger Audio-Session-
                    // Rekonfiguration laeuft (siehe scheduleWakeSegmentRestart).
                    scheduleWakeSegmentRestart()
                }
            } else if !isAutomaticSegment {
                teardownAudioEngine()
            }
        }
    }

    /// Switches from wake-word-only monitoring to capturing an actual command,
    /// the moment the wake word is recognized. Starts a genuinely FRESH
    /// recognition request rather than just flipping flags on the current
    /// one: SFSpeechRecognizer's `bestTranscription` is the full accumulated
    /// text since a request began, so simply clearing `liveTranscript` in
    /// place doesn't work - the very next partial result on the SAME request
    /// resends the whole accumulated string, "Jarvis" prefix included, and
    /// the field appeared to flicker as it kept getting clobbered back and
    /// forth (live-reported bug 2026-09-08). A fresh request accumulates
    /// from empty. The audio engine/tap themselves are untouched (still
    /// running from the wake segment), so this is cheap - no session/tap
    /// rework, see `isAudioEngineActive` in `beginRecognitionSegment`.
    private func beginCommandCaptureSegment() {
        isCapturingCommand = true
        try? beginRecognitionSegment(resetTranscript: true)
        resetSilenceTimer(initial: true)
    }

    /// `initial: true` is used right after the wake word fires (or a
    /// follow-up capture starts) when nothing has been said yet - gives the
    /// user real time to actually start talking ("Jarvis... [kurze Pause]
    /// ...wie ist das Wetter" is a completely normal speech pattern). Once
    /// real words are coming in, subsequent resets use the short interval to
    /// detect the end of the utterance promptly. Using the short interval
    /// for BOTH used to make the initial pause after saying the wake word
    /// itself trigger `evaluateCapturedCommand()` with an empty transcript,
    /// silently dropping back to wake-word-only listening before the user
    /// could say anything (live-reported bug 2026-09-08: "ich kann danach
    /// nichts ansagen, er reagiert dann gar nicht").
    private func resetSilenceTimer(initial: Bool = false) {
        silenceTimer?.invalidate()
        let interval = initial ? 4.0 : 1.5
        silenceTimer = Timer.scheduledTimer(withTimeInterval: interval, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.evaluateCapturedCommand() }
        }
    }

    /// Fires after a silence pause following wake-word activation (or during
    /// a follow-up capture): decides whether the utterance was an
    /// end-of-conversation phrase (publishes `pendingFarewell` - ChatView
    /// speaks the closing reply, then returns to wake-word-only listening)
    /// or a real command (publishes `pendingWakeCommand` for ChatView to send).
    private func evaluateCapturedCommand() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        let command = liveTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        teardownAudioEngine()
        isCapturingCommand = false

        guard !command.isEmpty else {
            if isWakeListening { beginWakeSegment() }
            return
        }

        if Self.isEndCommand(command) {
            liveTranscript = ""
            // KEIN sofortiges beginWakeSegment() hier - ChatView zeigt/spricht
            // erst noch die feste Abschieds-Antwort (siehe pendingFarewell)
            // und ruft danach resumeWakeWordListening() auf, sobald das
            // Sprechen fertig ist.
            pendingFarewell = Self.farewellReply
            return
        }

        pendingWakeCommand = command
    }

    /// Called by ChatView once it has sent `pendingWakeCommand`.
    func clearPendingWakeCommand() {
        pendingWakeCommand = nil
    }

    /// Called by ChatView once it has shown `pendingFarewell`.
    func clearPendingFarewell() {
        pendingFarewell = nil
    }

    /// Resumes pure wake-word-only listening (no follow-up capture) - used
    /// after speaking the farewell reply, so a genuinely NEW "Jarvis" is
    /// required again instead of continuing to capture whatever is said next.
    func resumeWakeWordListening() {
        guard isWakeListening, !isListening, !isSpeaking else { return }
        beginWakeSegment()
    }

    private func teardownAudioEngine() {
        // Prueft den physischen Engine-Status, nicht `isListening` - letzteres
        // wird waehrend eines internen Segment-Wechsels kurz auf false
        // gesetzt, obwohl Mikro/Engine weiterlaufen (siehe
        // `isAudioEngineActive`-Dokumentation oben). Ein Teardown-Aufruf genau
        // in dieser Luecke (z.B. stopWakeListening() vom Nutzer ausgeloest)
        // wuerde sonst faelschlich fruehzeitig zurueckkehren und das Mikro
        // verwaist weiterlaufen lassen.
        guard isAudioEngineActive else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        // Aktiv abbrechen statt nur die Referenz fallen zu lassen - sonst
        // kann der Speech-Framework-interne Task noch etwas spaeter (nach
        // endAudio()) ein "verspaetetes" Ergebnis/Fehler liefern. Die
        // Generation VOR diesem Callback hochzaehlen (nicht erst beim naechsten
        // Segment-Start) stellt sicher, dass so ein verspaeteter Callback vom
        // generation-Guard in beginRecognitionSegment() ignoriert wird, statt
        // faelschlich einen neuen Aktivierungswort-Neustart auszuloesen -
        // genau das killte bisher mitten in send()/speak() zufaellig
        // Jarvis' Sprachausgabe UND das Mikrofon des naechsten Redebeitrags,
        // weil ein solcher verspaeteter Callback die alte
        // isCapturingCommand/isWakeListening-Logik erneut durchlief (live
        // gemeldeter Bug 2026-09-08: nach der ersten Antwort mus staendig
        // erneut "Hey Jarvis" gesagt werden, und die Antwort blieb stumm).
        recognitionTask?.cancel()
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask = nil
        isListening = false
        isAudioEngineActive = false
        segmentGeneration += 1
        if !isWakeListening {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    /// Engages a playback-capable audio session BEFORE the network wait
    /// starts, not just once the reply text has arrived - iOS reliably lets
    /// an ALREADY-ACTIVE audio session continue through backgrounding, but
    /// does not reliably grant a FRESH audio session to a process that is
    /// already backgrounded by the time it tries to start playing (live bug
    /// 2026-09-07: replies that arrived while backgrounded sat silent until
    /// the app was reopened, because activation only truly took effect once
    /// back in the foreground). Call this right when a chat turn begins;
    /// harmless if speech ends up disabled or the reply is empty - an idle
    /// active session with nothing queued costs nothing.
    func prepareSpeechSessionForUpcomingReply() {
        stopListening()
        // .playAndRecord statt .playback - dieselbe Kategorie, die
        // beginRecognitionSegment() fuer die Aufnahme benutzt. Ein
        // anschliessendes Zuhoeren (z.B. startFollowUpListening()) muss dann
        // nur noch den MODUS wechseln (spokenAudio -> measurement), nicht die
        // ganze Kategorie - ein Kategoriewechsel reisst die Audio-Route ab
        // und neu auf, was genau in diesem Uebergang zu einem stummen/leeren
        // Mic-Tap fuehren konnte (live gemeldeter Bug 2026-09-08).
        try? AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .spokenAudio, options: [.duckOthers, .defaultToSpeaker])
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    /// Same German neural voice the old JARVIS-OS Mac project used
    /// (config.json: edge_voice) - Microsoft's free "edge-tts" via
    /// EdgeTTSClient.swift, tried FIRST since the user explicitly found
    /// Apple's on-device voice unsatisfying (live feedback 2026-09-08:
    /// "die Stimme ist komplett fürn Arsch"). Falls back to the Apple voice
    /// automatically if the network request fails - same resilience pattern
    /// as the old project's _speak_edge/_speak_macos fallback.
    private static let edgeVoiceName = "de-DE-KillianNeural"

    /// Speaks Jarvis's reply aloud - tries three tiers in order:
    /// 1. PiperVoiceEngine (on-device, no network at all - the reliable
    ///    default per the user's explicit request 2026-09-08, after the
    ///    direct-to-Microsoft and Mac-Mini-proxy Edge-TTS paths both proved
    ///    too fragile: Microsoft's bot detection blocked the former, the
    ///    latter kept failing over Tailscale despite real debugging effort -
    ///    macOS firewall permissions, buffered logs, etc.).
    /// 2. Edge-TTS via the Mac Mini proxy (kept as a safety net - should
    ///    essentially never be reached, since PiperVoiceEngine only returns
    ///    nil if the bundled model resources are somehow missing).
    /// 3. Apple's on-device synthesizer (always available, worst-sounding
    ///    but never fails outright).
    /// Awaits real completion (see `speakContinuation`/`edgePlaybackContinuation`
    /// above) rather than just returning once playback starts. Assumes
    /// `prepareSpeechSessionForUpcomingReply()` already ran (see
    /// ChatView.send()) - only re-engages the session here as a fallback for
    /// any OTHER caller that speaks without that priming step.
    func speak(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        // Mirrors the guard in startListening(): the mic and the speaker must
        // never be active at the same time on a phone, or the mic picks up
        // Jarvis's own voice as if it were new user input (live bug
        // 2026-09-07: a still-open recording session captured the TTS output
        // and fed it back in as a bogus follow-up message).
        stopListening()
        // Gleiche Begruendung wie in prepareSpeechSessionForUpcomingReply():
        // .playAndRecord statt .playback, damit ein anschliessendes Zuhoeren
        // nur den Modus wechselt statt die ganze Audio-Route neu aufzubauen.
        try? AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .spokenAudio, options: [.duckOthers, .defaultToSpeaker])
        try? AVAudioSession.sharedInstance().setActive(true)
        isSpeaking = true

        if let piperAudio = await synthesizePiperAudio(trimmed) {
            await playAudioData(piperAudio)
        } else {
            do {
                let audioData = try await EdgeTTS.synthesize(text: trimmed, voice: Self.edgeVoiceName)
                await playAudioData(audioData)
            } catch {
                errorMessage = "Edge-TTS fehlgeschlagen (\(error)) - nutze Apple-Stimme."
                await speakWithAppleVoice(trimmed)
            }
        }

        isSpeaking = false
    }

    /// PiperVoiceEngine's synthesis is synchronous, CPU-bound work - runs it
    /// off the main actor so a longer reply doesn't stall the UI while it
    /// renders.
    private func synthesizePiperAudio(_ text: String) async -> Data? {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let data = PiperVoiceEngine.synthesize(text)
                continuation.resume(returning: data)
            }
        }
    }

    private func playAudioData(_ data: Data) async {
        await withCheckedContinuation { continuation in
            guard let player = try? AVAudioPlayer(data: data) else {
                continuation.resume()
                return
            }
            player.delegate = self
            edgeAudioPlayer = player
            edgePlaybackContinuation = continuation
            guard player.play() else {
                edgeAudioPlayer = nil
                edgePlaybackContinuation = nil
                continuation.resume()
                return
            }
        }
    }

    private func speakWithAppleVoice(_ text: String) async {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.preferredGermanVoice()
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        await withCheckedContinuation { continuation in
            speakContinuation = continuation
            synthesizer.speak(utterance)
        }
    }

    func stopSpeaking() {
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        if let edgeAudioPlayer, edgeAudioPlayer.isPlaying {
            edgeAudioPlayer.stop()
            edgePlaybackContinuation?.resume()
            edgePlaybackContinuation = nil
        }
    }

    /// UserDefaults key backing SettingsView's manual voice picker - an
    /// explicit user choice there always wins over the automatic "best
    /// quality" fallback below.
    static let selectedVoiceIdentifierKey = "JarvisSelectedVoiceIdentifier"

    /// Uses the user's explicit pick from SettingsView if set; otherwise
    /// prefers an "Enhanced"/"Premium" quality German voice over the default
    /// compact one if the user has downloaded it (Settings > Accessibility >
    /// Spoken Content > Voices on the device) - falls back to whatever
    /// system default exists otherwise.
    private static func preferredGermanVoice() -> AVSpeechSynthesisVoice? {
        let germanVoices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("de") }
        let selectedIdentifier = UserDefaults.standard.string(forKey: selectedVoiceIdentifierKey) ?? ""
        if !selectedIdentifier.isEmpty, let chosen = germanVoices.first(where: { $0.identifier == selectedIdentifier }) {
            return chosen
        }
        if let premium = germanVoices.first(where: { $0.quality == .premium }) {
            return premium
        }
        if let enhanced = germanVoices.first(where: { $0.quality == .enhanced }) {
            return enhanced
        }
        return AVSpeechSynthesisVoice(language: "de-DE")
    }

    enum VoiceError: LocalizedError {
        case recognizerUnavailable
        case permissionDenied

        var errorDescription: String? {
            switch self {
            case .recognizerUnavailable: return "Spracherkennung ist gerade nicht verfügbar."
            case .permissionDenied: return "Mikrofon- oder Spracherkennungszugriff fehlt."
            }
        }
    }
}

extension VoiceManager: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
            self.speakContinuation?.resume()
            self.speakContinuation = nil
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
            self.speakContinuation?.resume()
            self.speakContinuation = nil
        }
    }
}

extension VoiceManager: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.edgePlaybackContinuation?.resume()
            self.edgePlaybackContinuation = nil
            self.edgeAudioPlayer = nil
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in
            self.edgePlaybackContinuation?.resume()
            self.edgePlaybackContinuation = nil
            self.edgeAudioPlayer = nil
        }
    }
}
