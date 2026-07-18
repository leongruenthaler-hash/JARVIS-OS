import SwiftUI

struct ChatBubble: View {
    let message: ChatMessage
    @Environment(\.jarvisTheme) private var theme
    @AppStorage("JarvisUserName") private var storedUserName = ""

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 80) }
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(message.text)
                    .textSelection(.enabled)
            }
            .padding(14)
            .background(background, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(borderColor, lineWidth: 1)
            )
            .shadow(color: shadowColor, radius: theme.isDark ? 14 : 8, x: 0, y: 3)
            if message.role != .user { Spacer(minLength: 80) }
        }
    }

    private var title: String {
        switch message.role {
        case .user: storedUserName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Nutzer" : storedUserName
        case .jarvis: "Jarvis"
        case .system: "System"
        }
    }

    private var background: some ShapeStyle {
        switch theme {
        case .futuristicBlue:
            switch message.role {
            case .user: return AnyShapeStyle(Color.blue.opacity(0.24))
            case .jarvis: return AnyShapeStyle(.ultraThinMaterial)
            case .system: return AnyShapeStyle(Color.cyan.opacity(0.12))
            }
        case .dashboard:
            switch message.role {
            case .user: return AnyShapeStyle(theme.primaryAccent.opacity(0.22))
            case .jarvis: return AnyShapeStyle(.ultraThinMaterial)
            case .system: return AnyShapeStyle(theme.secondaryAccent.opacity(0.16))
            }
        case .classic:
            switch message.role {
            case .user: return AnyShapeStyle(.blue.opacity(0.18))
            case .jarvis: return AnyShapeStyle(.ultraThinMaterial)
            case .system: return AnyShapeStyle(.orange.opacity(0.14))
            }
        }
    }

    private var borderColor: Color {
        switch theme {
        case .classic:
            return Color.white.opacity(0.12)
        case .futuristicBlue:
            switch message.role {
            case .user: return theme.primaryAccent.opacity(0.44)
            case .jarvis: return theme.secondaryAccent.opacity(0.32)
            case .system: return Color.cyan.opacity(0.28)
            }
        case .dashboard:
            switch message.role {
            case .user: return theme.primaryAccent.opacity(0.44)
            case .jarvis: return theme.secondaryAccent.opacity(0.32)
            case .system: return theme.primaryAccent.opacity(0.28)
            }
        }
    }

    private var shadowColor: Color {
        guard theme.isDark else { return Color.black.opacity(0.04) }
        return (message.role == .user ? theme.primaryAccent : theme.secondaryAccent).opacity(0.10)
    }
}
