import SwiftUI

/// Zeigt die echten OpenClaw-Automationen (Cronjobs) an - ersetzt die zuvor
/// migrierte, nie wirklich genutzte interne Aufgabenliste (2026-09-12,
/// Nutzerwunsch: "Aufgaben soll die Automationen anzeigen"). Rein lesend,
/// siehe scripts/automations_proxy_server.py.
struct AutomationsView: View {
    @EnvironmentObject private var appState: AppState

    private var enabledAutomations: [AutomationJob] {
        appState.automations.filter(\.enabled)
    }
    private var disabledAutomations: [AutomationJob] {
        appState.automations.filter { !$0.enabled }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                if appState.automations.isEmpty && !appState.automationsLoading {
                    Text("Keine Automationen gefunden.")
                        .foregroundStyle(.secondary)
                } else {
                    section("Aktiv", jobs: enabledAutomations, tint: .blue)
                    if !disabledAutomations.isEmpty {
                        section("Deaktiviert", jobs: disabledAutomations, tint: .secondary)
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Automationen")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshAutomations() }
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await appState.refreshAutomations() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "bolt.badge.clock", tint: .blue)
            VStack(alignment: .leading, spacing: 6) {
                Text("Automationen")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Wiederkehrende Hintergrund-Checks, die Jarvis selbstständig ausführt - z.B. Mail-Zusammenfassungen oder Termin-Erinnerungen. Steuerung (aktivieren/deaktivieren/anlegen) läuft weiterhin über das openclaw-Terminal.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    private func section(_ title: String, jobs: [AutomationJob], tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.title3.bold())
            VStack(spacing: 10) {
                ForEach(jobs) { job in
                    jobRow(job, tint: tint)
                }
            }
        }
    }

    private func jobRow(_ job: AutomationJob, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(job.name)
                        .font(.body.weight(.semibold))
                    if !job.description.isEmpty {
                        Text(job.description)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    HStack(spacing: 6) {
                        pill(job.schedule, tint: .purple)
                        pill(statusLabel(job.status), tint: statusTint(job.status))
                        if let lastRun = formattedDate(job.lastRunAtMs) {
                            pill("Zuletzt: \(lastRun)", tint: .secondary)
                        }
                        if let nextRun = formattedDate(job.nextRunAtMs) {
                            pill("Nächster Lauf: \(nextRun)", tint: .orange)
                        }
                    }
                    if let lastError = job.lastError, !lastError.isEmpty {
                        Text(lastError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
                Spacer(minLength: 12)
            }
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private func pill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(tint.opacity(0.12), in: Capsule())
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "ok": return "OK"
        case "skipped": return "Übersprungen"
        case "error": return "Fehler"
        case "idle": return "Wartend"
        default: return status
        }
    }

    private func statusTint(_ status: String) -> Color {
        switch status {
        case "ok": return .green
        case "error": return .red
        case "skipped": return .orange
        default: return .secondary
        }
    }

    private func formattedDate(_ millis: Double?) -> String? {
        guard let millis else { return nil }
        let date = Date(timeIntervalSince1970: millis / 1000)
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        formatter.locale = Locale(identifier: "de_DE")
        if Calendar.current.isDateInToday(date) {
            return formatter.string(from: date)
        }
        formatter.dateStyle = .short
        return formatter.string(from: date)
    }
}
