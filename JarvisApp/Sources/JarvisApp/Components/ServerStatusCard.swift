import SwiftUI

struct ServerStatusCard: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(appState.status.rawValue, systemImage: symbol)
                .font(.headline)
            HStack(spacing: 8) {
                statusChip(
                    title: appState.modelStatus.provider.lowercased() == "openai" ? "OpenAI aktiv" : "Lokal aktiv",
                    tint: appState.modelStatus.provider.lowercased() == "openai" ? .orange : .blue
                )
                statusChip(
                    title: appState.modelStatus.activeModel,
                    tint: .secondary
                )
            }
            if let error = appState.lastError {
                Text(error)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(theme.isFuturistic ? Color.black.opacity(0.22) : Color.clear)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(theme.isFuturistic ? theme.primaryAccent.opacity(0.36) : Color.white.opacity(0.16), lineWidth: 1)
        )
        .shadow(color: theme.primaryAccent.opacity(theme.isFuturistic ? 0.16 : 0.08), radius: theme.isFuturistic ? 22 : 16, x: 0, y: 8)
    }

    private func statusChip(title: String, tint: Color) -> some View {
        Text(title)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(tint)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(.thinMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(theme.isFuturistic ? theme.primaryAccent.opacity(0.24) : Color.white.opacity(0.12), lineWidth: 1))
    }

    private var symbol: String {
        switch appState.status {
        case .idle: "checkmark.circle"
        case .listening: "mic.circle"
        case .transcribing: "text.magnifyingglass"
        case .thinking: "brain.head.profile"
        case .responding: "waveform"
        case .offline: "exclamationmark.triangle"
        }
    }
}
