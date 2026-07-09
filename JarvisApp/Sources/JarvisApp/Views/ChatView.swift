import SwiftUI
import AppKit

struct ChatView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @State private var input = ""

    private var trimmedInput: String {
        input.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var latestJarvisText: String {
        appState.messages.last(where: { $0.role == .jarvis })?.text ?? "Ich bin bereit, \(appState.displayUserName). Drück das Mikrofon und sprich einfach los."
    }

    private var latestUserText: String? {
        appState.messages.last(where: { $0.role == .user })?.text
    }

    private var micDisabled: Bool {
        appState.voiceState == .preparingMicrophone ||
        appState.voiceState == .listening ||
        appState.voiceState == .userSpeaking ||
        appState.voiceState == .liveTranscribing ||
        appState.voiceState == .transcribing ||
        appState.voiceState == .thinking
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            themedDivider

            HStack(spacing: 0) {
                voiceStage
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                themedVerticalDivider

                conversationPanel
                    .frame(width: 360)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .layoutPriority(0)

            themedDivider
            inputBar
                .layoutPriority(2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(LiquidGlassBackground())
        .onAppear {
            if input.isEmpty, !appState.composerDraft.isEmpty {
                input = appState.composerDraft
                appState.clearComposerDraftIfMatches(appState.composerDraft)
            }
        }
        .onChange(of: appState.composerDraft) { _, newValue in
            guard !newValue.isEmpty else { return }
            input = newValue
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [activeVoiceTint.opacity(0.92), activeVoiceTint.opacity(0.44), Color.white.opacity(0.04)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                Image(systemName: appState.voiceState.symbol)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            .shadow(color: activeVoiceTint.opacity(theme.isFuturistic ? 0.34 : 0.18), radius: theme.isFuturistic ? 16 : 10, x: 0, y: 6)

            VStack(alignment: .leading, spacing: 4) {
                Text("Jarvis")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                Text("Dein ruhiger Assistent mit einem kleinen Hang zu trockenen Kommentaren.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    statusBadge
                    Text("Modell: \(appState.modelStatus.activeModel)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Text("Modus: \(modelModeLabel)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    if appState.modelStatus.provider.lowercased() == "openai" {
                        modelBadge(title: "OpenAI aktiv", tint: .orange)
                    } else {
                        modelBadge(title: "Lokal aktiv", tint: .blue)
                    }
                }
            }

            Spacer()

            if appState.voiceState == .jarvisSpeaking {
                Button {
                    Task { await appState.stopCurrentSpeech() }
                } label: {
                    Label("Stoppen", systemImage: "stop.fill")
                }
                .buttonStyle(.bordered)
                .help("Sprachausgabe sofort beenden")
            }
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 18)
    }

    private var statusBadge: some View {
        Label(appState.voiceState.title, systemImage: appState.voiceState.symbol)
            .font(.callout.weight(.medium))
            .foregroundStyle(activeVoiceTint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(theme.isFuturistic ? activeVoiceTint.opacity(0.42) : Color.white.opacity(0.16), lineWidth: 1))
            .shadow(color: activeVoiceTint.opacity(theme.isFuturistic ? 0.18 : 0.10), radius: 10, x: 0, y: 4)
    }

    private func modelBadge(title: String, tint: Color) -> some View {
        Text(title)
            .font(.callout.weight(.medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.16), lineWidth: 1))
            .shadow(color: tint.opacity(0.08), radius: 8, x: 0, y: 4)
    }

    private var voiceStage: some View {
        ScrollView {
            VStack(spacing: 18) {
                ZStack {
                    RoundedRectangle(cornerRadius: 36, style: .continuous)
                        .fill(.ultraThinMaterial)
                        .overlay(
                            RoundedRectangle(cornerRadius: 36, style: .continuous)
                                .strokeBorder(theme.isFuturistic ? theme.primaryAccent.opacity(0.36) : Color.white.opacity(0.14), lineWidth: 1)
                        )
                        .shadow(color: activeVoiceTint.opacity(theme.isFuturistic ? 0.16 : 0.08), radius: 24, x: 0, y: 10)

                    VStack(spacing: 14) {
                        Group {
                            if theme.isFuturistic {
                                JarvisGlowOrb(state: appState.voiceState, size: 240)
                            } else {
                                JarvisVoiceOrb(state: appState.voiceState, size: 240)
                            }
                        }
                        .padding(.top, 14)

                        VStack(spacing: 6) {
                            Text(appState.voiceState.title)
                                .font(.system(size: 30, weight: .bold, design: .rounded))
                            Text(appState.voiceState.subtitle)
                                .font(.title3)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                                .frame(maxWidth: 520)
                        }
                        .padding(.horizontal, 22)
                    }
                    .padding(.bottom, 18)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)

                moodStrip
                statusRibbon

                HStack(spacing: 12) {
                    Button {
                        Task { await appState.listenOnce() }
                    } label: {
                        Label(micButtonTitle, systemImage: micButtonSymbol)
                            .font(.title3.weight(.semibold))
                            .padding(.horizontal, 24)
                            .padding(.vertical, 12)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(micDisabled)
                    .keyboardShortcut(.space, modifiers: [.command])
                    .shadow(color: activeVoiceTint.opacity(theme.isFuturistic ? 0.20 : 0.10), radius: 10, x: 0, y: 6)

                    Button {
                        Task { await appState.stopAutoListening() }
                    } label: {
                        Label("Mikrofon deaktivieren", systemImage: "mic.slash.fill")
                            .font(.title3.weight(.semibold))
                            .padding(.horizontal, 18)
                            .padding(.vertical, 12)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(!canDeactivateMicrophone)
                    .help("Stoppt Jarvis beim Zuhören und beendet das automatische Weiterzuhören")
                }

                playfulHints
                    .padding(.top, 2)

                if let latestUserText {
                    VStack(spacing: 6) {
                        Text("Zuletzt verstanden")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(latestUserText)
                            .font(.callout)
                            .foregroundStyle(.primary)
                            .multilineTextAlignment(.center)
                            .lineLimit(3)
                            .frame(maxWidth: 560)
                    }
                    .padding(.top, 4)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity)
        }
        .background(LiquidGlassBackground())
    }

    private var playfulHints: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                hintPill("Bereit", icon: "sparkles", tint: .cyan)
                hintPill(appState.modelStatus.provider.lowercased() == "openai" ? "Cloud aktiv" : "Lokal aktiv", icon: appState.modelStatus.provider.lowercased() == "openai" ? "cloud.fill" : "house.fill", tint: appState.modelStatus.provider.lowercased() == "openai" ? .orange : .blue)
                hintPill(appState.lastAnswerSource.contains("OpenAI") ? "OpenAI-Antwort" : "Lokale Antwort", icon: "heart.text.square", tint: .pink)
            }
            ideaChips
        }
        .frame(maxWidth: 620)
    }

    private var ideaChips: some View {
        HStack(spacing: 8) {
            ideaChip("Was steht heute an?", symbol: "calendar.badge.clock") {
                appState.prepareComposerDraft("Jarvis, was steht heute an?")
            }
            ideaChip("Mail-Update", symbol: "envelope.open.fill") {
                appState.prepareComposerDraft("Jarvis, gib mir ein kurzes Mail-Update.")
            }
            ideaChip("Erinnerung", symbol: "bell.badge.fill") {
                appState.prepareComposerDraft("Jarvis, erstelle mir eine Erinnerung für morgen um 18 Uhr.")
            }
        }
        .frame(maxWidth: 620, alignment: .leading)
    }

    private var moodStrip: some View {
        HStack(spacing: 10) {
            vibePill("Sofort", icon: "bolt.fill", tint: .cyan)
            vibePill(appState.voiceState == .jarvisSpeaking ? "Jetzt spricht Jarvis" : "Bereit für den nächsten Satz", icon: appState.voiceState == .jarvisSpeaking ? "speaker.wave.2.fill" : "sparkles", tint: appState.voiceState == .jarvisSpeaking ? .orange : .green)
            vibePill(appState.voiceState == .thinking ? "Denkt nach" : "Reagiert direkt", icon: appState.voiceState == .thinking ? "brain.head.profile" : "arrow.triangle.2.circlepath", tint: .blue)
        }
        .frame(maxWidth: 620)
    }

    private func vibePill(_ title: String, icon: String, tint: Color) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.16), lineWidth: 1))
            .shadow(color: tint.opacity(0.08), radius: 8, x: 0, y: 4)
    }

    private func hintPill(_ title: String, icon: String, tint: Color) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.16), lineWidth: 1))
            .shadow(color: tint.opacity(0.08), radius: 8, x: 0, y: 4)
    }

    private func ideaChip(_ title: String, symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(.thinMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.14), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private var statusRibbon: some View {
        HStack(spacing: 10) {
            miniChip(title: appState.voiceState.title, icon: appState.voiceState.symbol, tint: appState.voiceState.tint)
            miniChip(title: appState.modelStatus.activeModel, icon: "cpu.fill", tint: .indigo)
            miniChip(title: modelModeLabel, icon: "speedometer", tint: .purple)
            miniChip(title: appState.lastAnswerSource, icon: appState.modelStatus.provider.lowercased() == "openai" ? "cloud.fill" : "house.fill", tint: appState.modelStatus.provider.lowercased() == "openai" ? .orange : .blue)
        }
        .frame(maxWidth: 560)
        .padding(.top, 6)
    }

    private var modelModeLabel: String {
        switch appState.modelStatus.mode.lowercased() {
        case "quality":
            return "Qualität"
        case "balanced":
            return "Ausgewogen"
        default:
            return "Performance"
        }
    }

    private func miniChip(title: String, icon: String, tint: Color) -> some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.14), lineWidth: 1))
    }

    private var micButtonTitle: String {
        switch appState.voiceState {
        case .jarvisSpeaking: return "Jarvis spricht"
        case .preparingMicrophone: return "Mikrofon startet"
        case .liveTranscribing: return "Live-Transkript läuft"
        case .transcribing: return "Transkription läuft"
        case .thinking: return "Verarbeitung läuft"
        case .listening, .userSpeaking: return "Ich höre zu"
        case .error: return "Erneut sprechen"
        case .idle: return "Mit Jarvis sprechen"
        }
    }

    private var micButtonSymbol: String {
        switch appState.voiceState {
        case .jarvisSpeaking: return "speaker.wave.2.fill"
        case .preparingMicrophone: return "mic.badge.plus"
        case .liveTranscribing, .transcribing: return "text.magnifyingglass"
        case .thinking: return "brain.head.profile"
        case .listening, .userSpeaking: return "waveform"
        case .error: return "arrow.clockwise"
        case .idle: return "mic.fill"
        }
    }

    private var conversationPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Antwort")
                    .font(.headline)
                HStack(spacing: 8) {
                    Text(appState.lastAnswerSource)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(appState.modelStatus.provider.lowercased() == "openai" ? .orange : .blue)
                    if appState.voiceState == .jarvisSpeaking {
                        Text("Live")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(.green)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 3)
                            .background(.thinMaterial, in: Capsule())
                    }
                }
                Text(latestJarvisText.isEmpty ? "..." : latestJarvisText)
                    .font(.callout)
                    .lineSpacing(2)
                    .textSelection(.enabled)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(18)

            Divider()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(appState.messages.suffix(8)) { message in
                        compactMessageRow(message)
                    }
                }
                .padding(18)
            }
        }
        .background(.ultraThinMaterial)
    }

    private func compactMessageRow(_ message: ChatMessage) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title(for: message.role))
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(message.text.isEmpty ? "..." : message.text)
                .font(.callout)
                .lineLimit(5)
                .textSelection(.enabled)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(messageBackground(for: message.role), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.10), lineWidth: 1)
                )
        }
        .padding(.trailing, 2)
    }

    private func title(for role: ChatMessage.Role) -> String {
        switch role {
        case .user: return appState.displayUserName
        case .jarvis: return "Jarvis"
        case .system: return "System"
        }
    }

    private func messageBackground(for role: ChatMessage.Role) -> some ShapeStyle {
        switch role {
        case .user: return AnyShapeStyle(Color.blue.opacity(0.14))
        case .jarvis: return AnyShapeStyle(Color.primary.opacity(0.07))
        case .system: return AnyShapeStyle(Color.orange.opacity(0.12))
        }
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Textmodus")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("Backup, falls du tippen willst.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            NativeTextField(
                placeholder: "Sekundäre Eingabe an Jarvis",
                text: $input,
                requestFocus: false,
                onCommit: send
            )
            .frame(height: 34)

            Button {
                send()
            } label: {
                Label("Senden", systemImage: "paperplane.fill")
                    .labelStyle(.titleAndIcon)
            }
            .keyboardShortcut(.return, modifiers: [.command])
            .disabled(trimmedInput.isEmpty)

            Button {
                Task { await appState.stopAutoListening() }
            } label: {
                Label("Mikrofon aus", systemImage: "mic.slash.fill")
                    .labelStyle(.titleAndIcon)
            }
            .disabled(!canDeactivateMicrophone)
            .help("Stoppt Jarvis beim Zuhören und beendet das automatische Weiterzuhören")
        }
        .padding(.horizontal, 22)
        .padding(.top, 14)
        .padding(.bottom, 20)
        .background(.ultraThinMaterial)
        .overlay(
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [Color.white.opacity(0.12), Color.clear],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(height: 1),
            alignment: .top
        )
    }

    private var isAutoListeningActive: Bool {
        appState.autoListenEnabled || appState.voiceState == .jarvisSpeaking
    }

    private var canDeactivateMicrophone: Bool {
        isAutoListeningActive ||
        appState.voiceState == .preparingMicrophone ||
        appState.voiceState == .listening ||
        appState.voiceState == .userSpeaking ||
        appState.voiceState == .liveTranscribing ||
        appState.voiceState == .transcribing
    }

    private var activeVoiceTint: Color {
        theme.isFuturistic ? theme.primaryAccent : appState.voiceState.tint
    }

    private var themedDivider: some View {
        Group {
            if theme.isFuturistic {
                JarvisDividerLine(tint: theme.primaryAccent)
            } else {
                Divider()
            }
        }
    }

    private var themedVerticalDivider: some View {
        Group {
            if theme.isFuturistic {
                Rectangle()
                    .fill(
                        LinearGradient(
                            colors: [.clear, theme.primaryAccent.opacity(0.36), .clear],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .frame(width: 1)
            } else {
                Divider()
            }
        }
    }

    private func send() {
        let text = trimmedInput
        guard !text.isEmpty else { return }
        input = ""
        Task { await appState.send(text) }
    }
}

struct NativeTextField: NSViewRepresentable {
    let placeholder: String
    @Binding var text: String
    let requestFocus: Bool
    let onCommit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text, onCommit: onCommit)
    }

    func makeNSView(context: Context) -> NSTextField {
        let field = CommitTextField()
        field.placeholderString = placeholder
        field.stringValue = text
        field.isEditable = true
        field.isSelectable = true
        field.isEnabled = true
        field.isBordered = true
        field.bezelStyle = .roundedBezel
        field.focusRingType = .default
        field.delegate = context.coordinator
        field.target = context.coordinator
        field.action = #selector(Coordinator.commit)
        field.onCommit = onCommit
        field.shouldRequestFocus = requestFocus

        if requestFocus {
            DispatchQueue.main.async {
                JarvisAppDelegate.activateJarvisWindow()
                field.window?.makeKeyAndOrderFront(nil)
                field.window?.makeFirstResponder(field)
            }
        }

        return field
    }

    func updateNSView(_ nsView: NSTextField, context: Context) {
        if nsView.stringValue != text {
            nsView.stringValue = text
        }
        if let field = nsView as? CommitTextField {
            field.onCommit = onCommit
            field.shouldRequestFocus = requestFocus
        }
        if requestFocus, nsView.window?.firstResponder == nil {
            DispatchQueue.main.async {
                JarvisAppDelegate.activateJarvisWindow()
                nsView.window?.makeKeyAndOrderFront(nil)
                nsView.window?.makeFirstResponder(nsView)
            }
        }
    }

    final class Coordinator: NSObject, NSTextFieldDelegate {
        @Binding var text: String
        let onCommit: () -> Void

        init(text: Binding<String>, onCommit: @escaping () -> Void) {
            self._text = text
            self.onCommit = onCommit
        }

        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSTextField else { return }
            text = field.stringValue
        }

        @objc func commit() {
            onCommit()
        }
    }
}

final class CommitTextField: NSTextField {
    var onCommit: (() -> Void)?
    var shouldRequestFocus = false

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard shouldRequestFocus else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            JarvisAppDelegate.activateJarvisWindow()
            self.window?.makeKeyAndOrderFront(nil)
            self.window?.makeFirstResponder(self)
        }
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 {
            onCommit?()
        } else {
            super.keyDown(with: event)
        }
    }
}
