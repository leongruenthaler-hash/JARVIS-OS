import SwiftUI

struct FeaturePlaceholderView: View {
    @EnvironmentObject private var appState: AppState
    let section: JarvisSection

    var body: some View {
        VStack(spacing: 22) {
            LiquidGlassIcon(symbol: section.symbol, tint: .cyan)
                .scaleEffect(1.18)

            VStack(spacing: 8) {
                Text(section.rawValue)
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text(description)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(2)
                    .frame(maxWidth: 560)
            }

            Button {
                appState.selectedSection = .chat
            } label: {
                Label("Im Chat mit Jarvis öffnen", systemImage: "bubble.left.and.bubble.right")
            }
            .buttonStyle(.borderedProminent)

            Text("Beta-Hinweis: Diese Fläche ist vorbereitet, aber noch nicht vollständig ausgeschrieben.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(LiquidGlassBackground())
        .overlay(
            RoundedRectangle(cornerRadius: 32, style: .continuous)
                .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)
                .padding(28)
                .allowsHitTesting(false)
        )
    }

    private var description: String {
        switch section {
        case .history:
            return "Hier bekommt Jarvis später eine saubere Verlaufsansicht. Bis dahin bleibt der Chat dein schneller Mittelpunkt."
        case .mail:
            return "Mail-Funktionen laufen bereits im Jarvis-Core. Diese Seite wird zur übersichtlichen Mail-Zentrale für Zusammenfassungen, Kategorien und Aktionen."
        case .calendar:
            return "Kalenderaktionen sind im Core vorbereitet. Diese Ansicht zeigt bereits echte Termine und Erinnerungen."
        case .reminders:
            return "Erinnerungen bleiben über Jarvis steuerbar. Die App-Seite zeigt geplante und offene Aufgaben direkt sichtbar an."
        case .files:
            return "Datei- und Desktop-Aktionen sind im Core vorhanden. Hier entsteht die visuelle Dateiverwaltung für Ordner, Rechnungen und Bewerbungen."
        case .photos:
            return "Der Fotoindex bleibt im Core. Diese Seite wird Suchergebnisse, Alben und Scanstatus schöner darstellen."
        default:
            return "Diese Ansicht ist vorbereitet und nutzt dieselbe lokale Jarvis-Schnittstelle. Die eigentliche Logik bleibt sauber im Python-Core."
        }
    }
}
