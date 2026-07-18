import SwiftUI

/// Shown instead of `ServerStatusCard` while the Python backend is bootstrapping for the
/// first time (Command Line Tools / venv / pip install). Deliberately neutral (blue, no
/// warning triangle) - this is expected one-time setup behavior, not an error, and should
/// not look like one.
struct SetupProgressCard: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)
                Text("Einmalige Ersteinrichtung läuft")
                    .font(.headline)
            }
            if let message = appState.bootstrapStatus {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text("Ein warmes MacBook und ein laufender Lüfter sind in dieser Phase normal - Jarvis installiert im Hintergrund benötigte Software. Das dauert einmalig bis zu 15-20 Minuten.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(theme.isDark ? Color.black.opacity(0.22) : Color.clear)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.blue.opacity(0.32), lineWidth: 1)
        )
        .shadow(color: Color.blue.opacity(theme.isDark ? 0.16 : 0.08), radius: theme.isDark ? 22 : 16, x: 0, y: 8)
    }
}
