import SwiftUI
import UIKit

struct ChatView: View {
    @State private var messages: [ChatMessage] = []
    @State private var draft = ""
    @State private var isSending = false
    @State private var errorMessage: String?
    // RemoteSettings.isPaired liest UserDefaults/Keychain direkt - ohne dieses
    // @State wuerde SwiftUI diese View nie neu zeichnen, wenn die Kopplung im
    // "Verbindung"-Tab erst NACH dem ersten Anzeigen dieses Tabs gesetzt wird
    // (Live-Bug 2026-09-06: Chat blieb dauerhaft auf "Noch nicht verbunden"
    // stehen, obwohl der Verbindungstest schon erfolgreich war).
    @State private var isPaired = RemoteSettings.isPaired
    @FocusState private var inputFocused: Bool
    @StateObject private var voice = VoiceManager()
    @StateObject private var keyboard = KeyboardObserver()
    /// Live "was Jarvis gerade tut"-Feed (2026-09-11) - geteilte Instanz von
    /// JarvisMobileApp.swift, siehe GatewayClient.swift. Ersetzt die bisherige reine
    /// Rate-Heuristik (Self.fillerPhrase) durch echte Server-Ereignisse, wo verfuegbar.
    @EnvironmentObject private var gateway: GatewayClient
    @AppStorage(VoiceManager.speakRepliesKey) private var speakRepliesAloud = true
    @AppStorage(VoiceManager.wakeListeningEnabledKey) private var wakeListeningEnabled = false

    private static let suggestions = [
        "Was liegt heute an?",
        "Fasse meine ungelesenen Mails zusammen",
        "Was steht als Nächstes im Kalender?",
        "Erzähl mir einen Witz"
    ]

    var body: some View {
        VStack(spacing: 0) {
            if !isPaired {
                ContentUnavailableView(
                    "Noch nicht verbunden",
                    systemImage: "network.slash",
                    description: Text("Richte die Verbindung zum Mac Mini im Tab \"Verbindung\" ein.")
                )
            } else if messages.isEmpty {
                welcomeState
            } else {
                messageList
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.horizontal)
                    .padding(.bottom, 4)
                    .transition(.opacity)
            }
            if let voiceError = voice.errorMessage {
                Text(voiceError)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.horizontal)
                    .padding(.bottom, 4)
            }

            // Normales VStack-Geschwister, KEIN zusaetzliches .safeAreaInset
            // mehr: das kombinierte sich mit KeyboardObserver's manuellem
            // Padding zu einem doppelt so grossen Abstand ueber der Tastatur
            // (gemeldeter Bug 2026-09-07, zweite Runde) - KeyboardObserver
            // ist jetzt die EINZIGE Quelle fuer den Tastatur-Abstand.
            if isPaired {
                inputBar
            }
        }
        .background(JarvisBackground())
        // Speist KeyboardObserver mit der tatsaechlichen unteren Kante DIESER
        // View (in globalen Fensterkoordinaten) statt der vollen
        // Bildschirmhoehe - siehe Kommentar in KeyboardObserver.swift.
        .background {
            GeometryReader { proxy in
                Color.clear
                    .onAppear { keyboard.viewMaxY = proxy.frame(in: .global).maxY }
                    .onChange(of: proxy.frame(in: .global).maxY) { _, newValue in
                        // NUR bei geschlossener Tastatur uebernehmen - sonst
                        // entsteht eine sich selbst verstaerkende
                        // Rueckkopplungsschleife: Tastatur oeffnet -> Hoehe
                        // gesetzt -> inputBar-Padding waechst -> Gesamthoehe
                        // dieses VStack aendert sich -> maxY aendert sich ->
                        // Tastaturhoehe wird (aus dem jetzt VERSCHOBENEN
                        // Referenzpunkt) neu berechnet -> Padding aendert
                        // sich wieder -> ... Das haengt den Hauptthread in
                        // einer Dauerschleife fest (live beobachtet
                        // 2026-09-10: App friert komplett ein, sobald man ins
                        // Textfeld tippt - nur ueber Force-Quit wieder
                        // loesbar). Bei geschlossener Tastatur ist maxY
                        // stabil und darf normal uebernommen werden (z.B.
                        // nach einer Drehung oder Dynamic-Type-Aenderung).
                        guard keyboard.height == 0 else { return }
                        keyboard.viewMaxY = newValue
                    }
            }
        }
        .preferredColorScheme(.dark)
        .navigationTitle("Jarvis")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: 8) {
                    Text("🤖")
                        .font(.title3)
                    Text("Jarvis")
                        .font(.headline)
                        .foregroundStyle(.white)
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    speakRepliesAloud.toggle()
                    if !speakRepliesAloud { voice.stopSpeaking() }
                } label: {
                    Image(systemName: speakRepliesAloud ? "speaker.wave.2.fill" : "speaker.slash.fill")
                        .foregroundStyle(speakRepliesAloud ? JarvisTheme.accent : JarvisTheme.textSecondary)
                }
                .help("Antworten vorlesen")
            }
        }
        .onAppear { isPaired = RemoteSettings.isPaired }
        .task { await activateWakeListeningIfEnabled() }
        .onChange(of: wakeListeningEnabled) { _, enabled in
            if enabled {
                Task { await activateWakeListeningIfEnabled() }
            } else {
                voice.stopWakeListening()
            }
        }
        .onChange(of: voice.pendingWakeCommand) { _, command in
            guard let command else { return }
            draft = command
            voice.clearPendingWakeCommand()
            Task { await send() }
        }
        .onChange(of: voice.pendingFarewell) { _, farewell in
            guard let farewell else { return }
            voice.clearPendingFarewell()
            Task { await handleFarewell(farewell) }
        }
    }

    /// Zeigt/spricht Jarvis' feste Abschieds-Antwort (siehe VoiceManager's
    /// `pendingFarewell`, 1:1 portiert aus dem alten JARVIS-OS-Backend) und
    /// kehrt danach zum reinen Aktivierungswort-Zuhoeren zurueck, statt wie
    /// nach einer normalen Antwort direkt weiter auf einen Folgesatz zu
    /// warten - genau das hat der Nutzer live angefordert 2026-09-08.
    private func handleFarewell(_ text: String) async {
        withAnimation { messages.append(ChatMessage(role: "assistant", content: text)) }
        if speakRepliesAloud {
            voice.prepareSpeechSessionForUpcomingReply()
            await voice.speak(text)
        }
        if wakeListeningEnabled && isPaired {
            voice.resumeWakeWordListening()
        }
    }

    /// Startet das kontinuierliche Aktivierungswort-Zuhoeren, falls in den
    /// Einstellungen eingeschaltet - fragt bei Bedarf zuerst nach den
    /// Mikrofon-/Spracherkennungs-Rechten.
    private func activateWakeListeningIfEnabled() async {
        guard wakeListeningEnabled, isPaired, !voice.isWakeListening, !voice.isListening else { return }
        let granted = await voice.requestPermissions()
        guard granted else {
            voice.errorMessage = "Mikrofon- oder Spracherkennungszugriff fehlt - bitte in den iOS-Einstellungen erlauben."
            return
        }
        voice.startWakeListening()
    }

    private var welcomeState: some View {
        VStack(spacing: 24) {
            Spacer()
            Text("🤖")
                .font(.system(size: 64))
            VStack(spacing: 6) {
                Text("Hey, ich bin Jarvis.")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(.white)
                Text("Frag mich einfach etwas - per Text oder Stimme.")
                    .font(.subheadline)
                    .foregroundStyle(JarvisTheme.textSecondary)
            }
            VStack(spacing: 10) {
                ForEach(Self.suggestions, id: \.self) { suggestion in
                    Button {
                        draft = suggestion
                        Task { await send() }
                    } label: {
                        Text(suggestion)
                            .font(.callout)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)
                            .background(JarvisTheme.cardFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(JarvisTheme.cardStroke, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 24)
            Spacer()
            Spacer()
        }
        // Ohne contentShape faengt ein VStack ohne eigenen Hintergrund nur
        // dort Taps ab, wo tatsaechlich Inhalt gerendert wird - die leeren
        // Spacer-Flaechen (der Grossteil dieser Ansicht vor der ersten
        // Nachricht) bleiben sonst tot fuers Tastatur-Schliessen-per-Tap.
        .contentShape(Rectangle())
        .onTapGesture { inputFocused = false }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(messages) { message in
                        ChatBubble(message: message)
                            .id(message.id)
                    }
                    if isSending {
                        TypingIndicator(activity: gateway.currentActivity, tools: gateway.activeTools)
                            .id("typing")
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .onChange(of: messages.count) { _, _ in
                scrollToBottom(proxy)
            }
            .onChange(of: isSending) { _, sending in
                if sending { scrollToBottom(proxy, anchorID: "typing") }
            }
            // Tastatur schliesst sich beim Antippen des Chatverlaufs (statt nur
            // ueber den Zeilenumbruch-Button oder einen Tab-Wechsel, der bei
            // offener Tastatur nicht zuverlaessig funktioniert - live gemeldet
            // 2026-09-10) und zusaetzlich beim Scrollen, damit man ohne
            // Umweg wieder an die unteren Tab-Symbole herankommt.
            .scrollDismissesKeyboard(.immediately)
            .onTapGesture { inputFocused = false }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, anchorID: AnyHashable? = nil) {
        let target = anchorID ?? messages.last?.id
        guard let target else { return }
        withAnimation(.easeOut(duration: 0.25)) {
            proxy.scrollTo(target, anchor: .bottom)
        }
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(voice.isListening ? "Ich höre zu..." : "Nachricht an Jarvis", text: $draft, axis: .vertical)
                .focused($inputFocused)
                .foregroundStyle(.white)
                .lineLimit(1...5)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(JarvisTheme.cardFill, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(voice.isListening ? JarvisTheme.accent.opacity(0.7) : JarvisTheme.cardStroke, lineWidth: 1))

            micButton

            Button {
                Task { await send() }
            } label: {
                Image(systemName: isSending ? "stop.circle.fill" : "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundStyle(canSend ? JarvisTheme.accentGradient : LinearGradient(colors: [.gray.opacity(0.4)], startPoint: .top, endPoint: .bottom))
            }
            .disabled(!canSend)
        }
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, keyboard.height > 0 ? keyboard.height + 44 : 10)
        .background(.ultraThinMaterial)
        .animation(.easeOut(duration: 0.25), value: keyboard.height)
        .onChange(of: voice.liveTranscript) { _, transcript in
            // Waehrend reinem Aktivierungswort-Lauschen (noch nicht erkannt)
            // dient liveTranscript nur als interne Treffer-Pruefung und darf
            // NICHT ins sichtbare Eingabefeld durchschlagen - sonst flackert
            // es mit jedem Hintergrundgeraeusch/Segment-Neustart an und aus
            // (live gemeldeter Bug 2026-09-08). Bei manueller Aufnahme
            // (isWakeListening == false) oder einer echten Befehlserfassung
            // (isCapturingCommand == true) soll es wie gewohnt live anzeigen.
            guard !voice.isWakeListening || voice.isCapturingCommand else { return }
            draft = transcript
        }
    }

    private var micButton: some View {
        Button {
            Task { await toggleListening() }
        } label: {
            Image(systemName: voice.isSpeaking ? "speaker.wave.2.fill" : (voice.isListening ? "mic.fill" : "mic"))
                .font(.system(size: 20))
                .foregroundStyle(voice.isListening ? .white : (voice.isSpeaking ? JarvisTheme.textSecondary : JarvisTheme.accent))
                .frame(width: 36, height: 36)
                .background(voice.isListening ? AnyShapeStyle(JarvisTheme.accentGradient) : AnyShapeStyle(JarvisTheme.cardFill), in: Circle())
                .overlay(Circle().strokeBorder(JarvisTheme.cardStroke, lineWidth: voice.isListening ? 0 : 1))
        }
        .disabled(isSending)
    }

    private var canSend: Bool {
        !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func toggleListening() async {
        // Ein Tap waehrend Jarvis spricht unterbricht NUR die Sprachausgabe -
        // startet noch nicht das Zuhoeren. Das erzwingt einen zweiten, bewusst
        // separaten Tap, bevor tatsaechlich aufgenommen wird, und schliesst
        // damit den Feedback-Loop aus (Mikro faengt sonst die eigene, gerade
        // erst gestoppte TTS-Ausgabe als vermeintliche neue Nachricht ein -
        // live gemeldeter Bug 2026-09-07).
        if voice.isSpeaking {
            voice.stopSpeaking()
            return
        }
        if voice.isListening {
            // Stoppt NUR die Aufnahme - schickt NICHT automatisch ab. Der
            // erkannte Text bleibt im editierbaren Eingabefeld stehen, damit
            // der Nutzer ihn gegenlesen/korrigieren kann, falls die
            // Spracherkennung etwas falsch verstanden hat (live gemeldeter
            // Wunsch 2026-09-07) - erst ein bewusster Tap auf "Senden" schickt
            // die Nachricht wirklich ab, wie beim normalen Tippen auch.
            voice.stopListening()
            inputFocused = true
            return
        }
        let granted = await voice.requestPermissions()
        guard granted else {
            voice.errorMessage = "Mikrofon- oder Spracherkennungszugriff fehlt - bitte in den iOS-Einstellungen erlauben."
            return
        }
        // Manuelles Zuhoeren hat Vorrang - das kontinuierliche Aktivierungswort-
        // Zuhoeren erst stoppen, damit sich beide Modi nicht denselben
        // Audio-Tap streitig machen.
        voice.stopWakeListening()
        do {
            try voice.startListening()
        } catch {
            voice.errorMessage = error.localizedDescription
        }
    }

    private func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        errorMessage = nil
        // Mikro sofort beim Abschicken hart deaktivieren, nicht erst wenn
        // speak() spaeter beim Eintreffen der Antwort laeuft - garantiert das
        // unabhaengig davon, ueber welchen Pfad send() ausgeloest wurde
        // (live gewuenscht 2026-09-07: Mikro soll direkt nach dem Abschicken
        // wieder aus sein, nicht erst wenn Jarvis zu sprechen beginnt).
        voice.stopListening()
        // Audio-Sitzung schon HIER aktivieren, nicht erst wenn die Antwort da
        // ist - iOS laesst eine bereits aktive Sitzung zuverlaessig durch
        // Backgrounding weiterlaufen, gewaehrt aber einer schon
        // hintergrundlaufenden App keine neue Audio-Aktivierung zuverlaessig
        // (live gemeldeter Bug 2026-09-07, zweite Runde: Antwort kam im
        // Hintergrund an, sprach aber erst beim Zurueckkehren in die App).
        if speakRepliesAloud {
            voice.prepareSpeechSessionForUpcomingReply()
        }
        withAnimation { messages.append(ChatMessage(role: "user", content: text)) }
        isSending = true
        defer { isSending = false }

        let history = messages.map { ["role": $0.role, "content": $0.content] }
        // Waehrend der Netzwerk-Antwort laeuft weder Mikro noch Sprachausgabe -
        // ohne aktive Audio-Sitzung hat iOS keinen Grund, die App im
        // Hintergrund am Leben zu halten, und killt die Anfrage nach wenigen
        // Sekunden (live gemeldeter Bug 2026-09-07: "wenn Jarvis nachdenkt und
        // ich die App wegwische, bricht alles ab"). Eine explizite Background-
        // Task-Anmeldung gibt iOS einen eigenstaendigen Grund, weiterlaufen
        // zu lassen, unabhaengig vom Audio-Session-Status.
        var backgroundTaskID = UIBackgroundTaskIdentifier.invalid
        backgroundTaskID = UIApplication.shared.beginBackgroundTask(withName: "jarvis-chat-response") {
            UIApplication.shared.endBackgroundTask(backgroundTaskID)
            backgroundTaskID = .invalid
        }
        defer {
            if backgroundTaskID != .invalid {
                UIApplication.shared.endBackgroundTask(backgroundTaskID)
            }
        }

        // ChatGPT-Live-artige Zwischenansage (live gewuenscht 2026-09-09): wenn
        // die Antwort nicht innerhalb kurzer Zeit da ist - meist, weil Jarvis
        // gerade ein laengeres Werkzeug ausfuehrt (Mails durchsuchen,
        // Kalender bearbeiten, Musik steuern) statt nur zu antworten - sagt
        // Jarvis kurz von sich aus etwas wie "einen Moment, ich schau nach",
        // statt die ganze Wartezeit ueber stumm zu bleiben. Rein
        // client-seitige Heuristik (Stichwortabgleich auf die eigene
        // Nachricht) - OpenClaw selbst meldet keine Zwischenstaende zurueck,
        // da der Chat nicht gestreamt ist.
        let fillerTask: Task<Void, Never>? = speakRepliesAloud ? Task {
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            guard !Task.isCancelled else { return }
            await voice.speak(Self.fillerPhrase(for: text))
        } : nil

        do {
            let response = try await APIClient().sendChat(text, history: history)
            fillerTask?.cancel()
            // Falls die Zwischenansage schon zu sprechen begonnen hat, erst zu
            // Ende sprechen lassen statt sie mitten im Satz abzuwuergen - nur
            // ein NICHT begonnener Timer laesst sich durch cancel() wirklich
            // stoppen.
            while voice.isSpeaking {
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            withAnimation { messages.append(ChatMessage(role: "assistant", content: response.answer)) }
            if speakRepliesAloud {
                await voice.speak(response.answer)
            }
            // Nach der Antwort direkt weiterhoeren, ohne dass "Jarvis" erneut
            // gesagt werden muss - wie beim alten Jarvis-System (live gewuenscht
            // 2026-09-07). Faellt automatisch auf reines Aktivierungswort-
            // Zuhoeren zurueck, sobald der Nutzer schweigt oder eine
            // Abschluss-Floskel sagt (siehe VoiceManager.evaluateCapturedCommand()).
            if wakeListeningEnabled && isPaired {
                await voice.startFollowUpListening()
            }
        } catch {
            fillerTask?.cancel()
            errorMessage = error.localizedDescription
        }
    }

    /// Stichwortabgleich auf die eigene Nachricht - rein clientseitige
    /// Vermutung, WAS Jarvis wohl gerade tut, nicht auf OpenClaws
    /// tatsaechliches Verhalten. Absichtlich grob statt praezise: eine
    /// halbwegs passende Zwischenansage ist besser als stures Schweigen,
    /// aber es lohnt sich nicht, das perfekt zu treffen.
    private static func fillerPhrase(for text: String) -> String {
        let lower = text.lowercased()
        if lower.contains("mail") || lower.contains("e-mail") {
            return "Einen Moment, ich schau in deinen Mails nach."
        }
        if lower.contains("kalender") || lower.contains("termin") {
            return "Ich schau kurz in deinen Kalender."
        }
        if lower.contains("musik") || lower.contains("lied") || lower.contains("song") || lower.contains("playlist") || lower.contains("abspiel") {
            return "Ich bin dran, einen Moment."
        }
        if lower.contains("foto") || lower.contains("bild") {
            return "Ich durchsuche deine Fotos, einen Moment."
        }
        if lower.contains("datei") || lower.contains("dokument") {
            return "Ich schau in deinen Dateien nach."
        }
        let generic = [
            "Einen Moment, ich schau mal nach.",
            "Ich bin gleich so weit.",
            "Lass mich kurz nachdenken.",
            "Ich kümmere mich darum, einen Augenblick.",
        ]
        return generic.randomElement() ?? generic[0]
    }
}

private struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if message.role == "user" { Spacer(minLength: 48) }

            if message.role != "user" {
                Text("🤖")
                    .font(.system(size: 20))
                    .frame(width: 28, height: 28)
            }

            Text(message.content)
                .font(.body)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background {
                    if message.role == "user" {
                        JarvisTheme.accentGradient
                    } else {
                        JarvisTheme.cardFill
                    }
                }
                .foregroundStyle(message.role == "user" ? Color.black : Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay {
                    if message.role != "user" {
                        RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(JarvisTheme.cardStroke, lineWidth: 1)
                    }
                }

            if message.role != "user" { Spacer(minLength: 48) }
        }
        .transition(.asymmetric(insertion: .move(edge: .bottom).combined(with: .opacity), removal: .opacity))
    }
}

/// Animated three-dot indicator shown while waiting for Jarvis's response -
/// makes the wait feel alive instead of a frozen UI (ChatGPT-style). When live
/// Gateway events are available (2026-09-11, GatewayClient.swift), shows what Jarvis is
/// actually doing (session.observer headline + running tool names) instead of just dots.
private struct TypingIndicator: View {
    let activity: String?
    let tools: [GatewayClient.ActiveTool]

    @State private var phase = 0

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text("🤖")
                .font(.system(size: 20))
                .frame(width: 28, height: 28)
            VStack(alignment: .leading, spacing: 4) {
                if let activity {
                    Text(activity)
                        .font(.callout)
                        .foregroundStyle(.white)
                }
                if !tools.isEmpty {
                    Text(tools.map(\.title).joined(separator: " · "))
                        .font(.caption2)
                        .foregroundStyle(JarvisTheme.accent)
                        .lineLimit(1)
                }
                if activity == nil && tools.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(0..<3, id: \.self) { index in
                            Circle()
                                .frame(width: 7, height: 7)
                                .foregroundStyle(JarvisTheme.textSecondary)
                                .opacity(phase == index ? 1 : 0.3)
                        }
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(JarvisTheme.cardFill)
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(JarvisTheme.cardStroke, lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            Spacer(minLength: 48)
        }
        .animation(.easeOut(duration: 0.2), value: activity)
        .animation(.easeOut(duration: 0.2), value: tools)
        .onAppear {
            Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { timer in
                guard isSendingStillRelevant else { timer.invalidate(); return }
                withAnimation { phase = (phase + 1) % 3 }
            }
        }
    }

    // Timer has no owning-view lifecycle hook beyond onAppear/onDisappear;
    // this view is removed from the hierarchy as soon as sending finishes
    // (see ChatView's `if isSending`), so the timer naturally stops firing
    // useful updates - `true` here just avoids over-engineering a view that
    // lives for, at most, a few seconds.
    private var isSendingStillRelevant: Bool { true }
}

#Preview {
    NavigationStack { ChatView() }
}
