import SwiftUI

struct ModelsView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @State private var showOpenAIConfirmation = false

    private let localModels: [LocalModelOption] = [
        LocalModelOption(
            title: "phi4-mini",
            subtitle: "Standardmodell",
            detail: "Schnell, lokal und ideal für Alltag, Befehle und Systemaufgaben.",
            model: "phi4-mini",
            symbol: "bolt.fill"
        ),
        LocalModelOption(
            title: "gemma3:4b",
            subtitle: "Lokale Premiumqualität",
            detail: "Etwas stärker für längere Antworten und natürlichere Formulierungen.",
            model: "gemma3:4b",
            symbol: "sparkles",
            downloadSizeHint: "3,3 GB"
        ),
        LocalModelOption(
            title: "qwen3:4b",
            subtitle: "Lokale höchste Qualität",
            detail: "Stark für komplexere Aufgaben, braucht aber etwas mehr Geduld.",
            model: "qwen3:4b",
            symbol: "brain.head.profile",
            downloadSizeHint: "2,5 GB"
        )
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                statusGrid
                localModelsSection
                openAISection
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Modelle")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshStatus() }
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await appState.refreshStatus() }
        .confirmationDialog(
            "OpenAI aktivieren?",
            isPresented: $showOpenAIConfirmation,
            titleVisibility: .visible
        ) {
            Button("OpenAI aktivieren") {
                Task { await appState.switchModel(provider: "openai") }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Dabei können Anfragen an OpenAI gesendet werden. Jarvis nutzt Cloud-KI nur, wenn du das ausdrücklich aktivierst und ein API-Key in der Keychain liegt.")
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "cpu", tint: .indigo)

            VStack(alignment: .leading, spacing: 6) {
                Text("Modellsteuerung")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Wähle, ob Jarvis lokal mit Ollama arbeitet oder optional OpenAI nutzt. Lokal bleibt der Standard.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private var statusGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), spacing: 14)], spacing: 14) {
            statusCard(
                title: "Aktives Modell",
                value: appState.modelStatus.activeModel,
                symbol: "checkmark.seal.fill",
                tint: .green
            )
            statusCard(
                title: "Betriebsart",
                value: appState.modelStatus.openAIEnabled ? "Cloud aktiv" : "Lokal aktiv",
                symbol: appState.modelStatus.openAIEnabled ? "cloud.fill" : "house.fill",
                tint: appState.modelStatus.openAIEnabled ? .orange : (theme.isDark ? theme.primaryAccent : .blue)
            )
            statusCard(
                title: "Modus",
                value: modeLabel,
                symbol: "speedometer",
                tint: .purple
            )
            statusCard(
                title: "Ollama",
                value: appState.modelStatus.ollamaRunning ? "Erreichbar" : "Nicht erreichbar",
                symbol: appState.modelStatus.ollamaRunning ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                tint: appState.modelStatus.ollamaRunning ? .green : .orange
            )
            statusCard(
                title: "OpenAI Key",
                value: appState.modelStatus.openAIKeyPresent ? "In Keychain" : "Fehlt",
                symbol: appState.modelStatus.openAIKeyPresent ? "key.fill" : "key.slash.fill",
                tint: appState.modelStatus.openAIKeyPresent ? .green : .secondary
            )
        }
    }

    private var modeLabel: String {
        switch appState.modelStatus.mode.lowercased() {
        case "quality":
            return "Qualität"
        case "balanced":
            return "Ausgewogen"
        default:
            return "Performance"
        }
    }

    private func statusCard(title: String, value: String, symbol: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 34, height: 34)
                .background(theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.045)) : AnyShapeStyle(.thinMaterial), in: Circle())

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }

            Spacer(minLength: 0)
        }
        .padding(14)
        .liquidGlassCard(tint: tint, cornerRadius: 20)
    }

    private var localModelsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Lokale Modelle", subtitle: "Kostenlos über Ollama. Keine Cloud, keine API-Kosten.")

            VStack(spacing: 12) {
                ForEach(localModels) { option in
                    localModelCard(option)
                }
            }
        }
    }

    private func localModelCard(_ option: LocalModelOption) -> some View {
        let installed = isInstalled(option.model)
        let active = isActiveLocalModel(option.model)

        return VStack(alignment: .leading, spacing: 14) {
            if installed {
                Button {
                    Task { await appState.switchModel(provider: "ollama", model: option.model) }
                } label: {
                    localModelRow(option, installed: true, active: active)
                }
                .buttonStyle(.plain)
            } else {
                localModelRow(option, installed: false, active: false)
                modelDownloadControls(option)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(cardBackground(active: active), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(active ? Color.green.opacity(0.35) : Color.white.opacity(0.18), lineWidth: 1)
        )
        .shadow(color: (active ? Color.green : Color.indigo).opacity(0.08), radius: 18, x: 0, y: 10)
    }

    private func localModelRow(_ option: LocalModelOption, installed: Bool, active: Bool) -> some View {
        HStack(spacing: 14) {
            Image(systemName: option.symbol)
                .font(.system(size: 21, weight: .semibold))
                .foregroundStyle(active ? .green : .primary)
                .frame(width: 42, height: 42)
                .background(theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.045)) : AnyShapeStyle(.thinMaterial), in: RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(option.title)
                        .font(.headline)
                    pill(installed ? "Installiert" : "Fehlt", color: installed ? .green : .orange)
                    if active {
                        pill("Aktiv", color: theme.isDark ? theme.primaryAccent : .blue)
                    }
                }
                Text(option.subtitle)
                    .font(.callout.weight(.medium))
                Text(option.detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()

            if active {
                Image(systemName: "checkmark.circle.fill")
                    .font(.title3)
                    .foregroundStyle(.green)
            } else if installed {
                Image(systemName: "arrow.right.circle")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func modelDownloadControls(_ option: LocalModelOption) -> some View {
        let isPullingThis = isPulling(option.model)
        let failedThis = pullFailed(option.model)

        if isPullingThis {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(appState.modelPullProgress.currentLabel)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(appState.modelPullProgress.percentText)
                        .font(.callout.monospacedDigit().weight(.semibold))
                }
                ProgressView(value: appState.modelPullProgress.totalItems > 0 ? appState.modelPullProgress.fraction : nil)
                    .progressViewStyle(.linear)
            }
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Button {
                    Task { await appState.pullModel(option.model) }
                } label: {
                    Label(
                        failedThis ? "Erneut versuchen" : "Herunterladen (\(option.downloadSizeHint))",
                        systemImage: "arrow.down.circle"
                    )
                }
                .buttonStyle(.borderedProminent)

                if failedThis, let error = appState.modelPullProgress.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
        }
    }

    private func isPulling(_ model: String) -> Bool {
        normalized(appState.modelPullProgress.stats["model"]?.description ?? "") == normalized(model)
            && [.preparing, .downloading].contains(appState.modelPullProgress.status)
    }

    private func pullFailed(_ model: String) -> Bool {
        normalized(appState.modelPullProgress.stats["model"]?.description ?? "") == normalized(model)
            && appState.modelPullProgress.status == .failed
    }

    private var openAISection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("OpenAI", subtitle: "Optional. Nur mit Keychain-Key und deiner bewussten Aktivierung.")

            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: "cloud")
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(appState.modelStatus.openAIEnabled ? .orange : .secondary)
                        .frame(width: 44, height: 44)
                        .background(theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.045)) : AnyShapeStyle(.thinMaterial), in: RoundedRectangle(cornerRadius: 14, style: .continuous))

                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 8) {
                            Text("OpenAI GPT-5 Nano")
                                .font(.headline)
                            pill(appState.modelStatus.openAIEnabled ? "Aktiv" : "Inaktiv", color: appState.modelStatus.openAIEnabled ? .orange : .secondary)
                            pill(appState.modelStatus.openAIKeyPresent ? "Key vorhanden" : "Key fehlt", color: appState.modelStatus.openAIKeyPresent ? .green : .orange)
                        }
                        Text("Cloud-KI bleibt ausgeschaltet, bis du sie aktivierst.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Spacer()
                }

                HStack(spacing: 10) {
                    Button {
                        Task { await appState.switchModel(provider: "ollama", model: "phi4-mini") }
                    } label: {
                        Label("Lokal arbeiten", systemImage: "house.fill")
                    }
                    .buttonStyle(.borderedProminent)

                    Button {
                        if appState.modelStatus.openAIKeyPresent {
                            showOpenAIConfirmation = true
                        } else {
                            appState.selectedSection = .settings
                        }
                    } label: {
                        Label(appState.modelStatus.openAIKeyPresent ? "OpenAI aktivieren" : "API-Key hinterlegen", systemImage: appState.modelStatus.openAIKeyPresent ? "cloud.fill" : "key.fill")
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(16)
            .background(theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.03)) : AnyShapeStyle(.ultraThinMaterial), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
            )
            .shadow(color: Color.orange.opacity(0.08), radius: 18, x: 0, y: 10)
        }
    }

    private func sectionHeader(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title2.bold())
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private func pill(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
    }

    private func cardBackground(active: Bool) -> some ShapeStyle {
        if active { return AnyShapeStyle(Color.green.opacity(0.12)) }
        return theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.03)) : AnyShapeStyle(.ultraThinMaterial)
    }

    private func isActiveLocalModel(_ model: String) -> Bool {
        !appState.modelStatus.openAIEnabled && normalized(appState.modelStatus.activeModel) == normalized(model)
    }

    private func isInstalled(_ model: String) -> Bool {
        appState.modelStatus.installedModels.contains { installed in
            normalized(installed) == normalized(model)
        }
    }

    private func normalized(_ model: String) -> String {
        model.hasSuffix(":latest") ? String(model.dropLast(7)) : model
    }
}

private struct LocalModelOption: Identifiable {
    let title: String
    let subtitle: String
    let detail: String
    let model: String
    let symbol: String
    var downloadSizeHint: String = ""

    var id: String { model }
}
