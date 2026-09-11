import SwiftUI

struct MailView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme

    private var mailAllowed: Bool {
        appState.permissions["mail"]?.allowed ?? false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionNotice
                scanStatusSection
                actionGrid
                summariesSection
                resultPanel
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Mail")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.performMailCommand("Jarvis, prüfe meinen Mail-Status.") }
                } label: {
                    Label("Prüfen", systemImage: "arrow.clockwise")
                }
                .disabled(!mailAllowed || appState.mailIsLoading)
            }
        }
        .task {
            await appState.refreshPermissions()
            await appState.refreshScanStatesSafely()
            await appState.loadMailSummaries()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "envelope.fill", tint: .blue)

            VStack(alignment: .leading, spacing: 6) {
                Text("Mail-Zentrale")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Jarvis scannt Apple Mail, fasst Wichtiges zusammen und arbeitet dabei strikt innerhalb deiner Berechtigung.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    @ViewBuilder
    private var permissionNotice: some View {
        if mailAllowed {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.shield.fill")
                    .foregroundStyle(.green)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Mail-Berechtigung aktiv")
                        .font(.headline)
                    Text("Jarvis darf Mail-Übersichten für angefragte Aufgaben lesen. Löschen, Verschieben oder Senden bleibt bestätigungspflichtig.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .liquidGlassPanel(tint: .green)
        } else {
            HStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Mail-Berechtigung ist blockiert")
                        .font(.headline)
                    Text("Aktiviere Mail in der Datenschutz-Seite, bevor Jarvis Apple Mail liest. Apple selbst fragt zusätzlich nach Automation-Freigabe, falls nötig.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Datenschutz öffnen") {
                    appState.selectedSection = .privacy
                }
                .buttonStyle(.borderedProminent)
            }
            .liquidGlassPanel(tint: .orange)
        }
    }

    private var actionGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 14)], spacing: 14) {
            mailActionCard(
                title: "Status prüfen",
                subtitle: "Testet Zugriff und liest erste Übersichten.",
                symbol: "stethoscope",
                command: "Jarvis, prüfe meinen Mail-Status."
            )
            mailActionCard(
                title: "Ordner scannen",
                subtitle: "Zeigt sichtbare Apple-Mail-Ordner und Nachrichtenanzahl.",
                symbol: "tray.full.fill",
                command: "Jarvis, scanne meine Mail-Ordner.",
                action: { await appState.startMailFolderScan() }
            )
            mailActionCard(
                title: "Inbox zusammenfassen",
                subtitle: "Fasst iCloud INBOX kurz und gesprochen zusammen.",
                symbol: "text.redaction",
                command: "Jarvis, fasse meine Mails aus iCloud INBOX zusammen."
            )
            mailActionCard(
                title: "Letzte 24 Stunden",
                subtitle: "Priorisiert neue Mails und zeitnahe Themen.",
                symbol: "clock.badge.checkmark.fill",
                command: "Jarvis, fasse meine Mails aus iCloud INBOX der letzten 24 Stunden zusammen."
            )
            mailActionCard(
                title: "Archiv zusammenfassen",
                subtitle: "Liest den iCloud-Archivordner als Übersicht.",
                symbol: "archivebox.fill",
                command: "Jarvis, fasse mir die Mails aus Archiv zusammen."
            )
            mailActionCard(
                title: "Zusammenfassungen aktualisieren",
                subtitle: "Läuft automatisch im Hintergrund - hier nur neu laden.",
                symbol: "moon.stars.fill",
                command: "",
                action: { await appState.startMailBackgroundScan() }
            )
            mailActionCard(
                title: "Dokumente kopieren",
                subtitle: "Rechnungen, Versicherungen und Abos auf den Schreibtisch vorbereiten.",
                symbol: "doc.badge.arrow.up.fill",
                command: "Jarvis, kopiere Rechnungen, Versicherungen und Abonnements aus meinen Mails auf meinen Schreibtisch."
            )
        }
    }

    private var scanStatusSection: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 14)], spacing: 14) {
            ScanProgressCard(
                title: "Mail-Scan",
                symbol: "tray.full",
                progress: appState.mailScanProgress,
                stats: [
                    ("Ordner gefunden", stat(appState.mailScanProgress, "folders_found")),
                    ("Ordner gescannt", stat(appState.mailScanProgress, "folders_scanned")),
                    ("Mails gefunden", stat(appState.mailScanProgress, "mails_found")),
                    ("Mails indexiert", stat(appState.mailScanProgress, "mails_indexed")),
                    ("Aktueller Ordner", stat(appState.mailScanProgress, "current_folder")),
                    ("Letzter Scan", stat(appState.mailScanProgress, "last_successful_scan"))
                ]
            )
        }
    }

    /// Ersetzt die alte, gebuendelte "Mail-Hintergrundscan"-Statuskarte
    /// (2026-09-12): jede von der "mail-summary-watch"-Automation zusammengefasste
    /// Mail bekommt hier ihre eigene, einzeln sichtbare Karte statt einem
    /// gemeinsamen Fortschrittsbalken.
    @ViewBuilder
    private var summariesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Mail-Zusammenfassungen", systemImage: "list.bullet.rectangle.portrait")
                    .font(.title3.bold())
                Spacer()
                Button {
                    Task { await appState.loadMailSummaries() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
            }

            if appState.mailSummaries.isEmpty {
                Text("Noch keine Zusammenfassungen - Jarvis fasst neue Mails automatisch im Hintergrund zusammen.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(appState.mailSummaries) { entry in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(entry.subject.isEmpty ? "(ohne Betreff)" : entry.subject)
                                    .font(.headline)
                                    .lineLimit(1)
                                Spacer()
                                Text(entry.received)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Text(entry.sender)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                            Text(entry.summary)
                                .font(.callout)
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                }
            }
        }
        .liquidGlassPanel(tint: .blue)
    }

    private func mailActionCard(
        title: String,
        subtitle: String,
        symbol: String,
        command: String,
        action: (() async -> Void)? = nil
    ) -> some View {
        Button {
            Task {
                if let action {
                    await action()
                } else {
                    await appState.performMailCommand(command)
                }
            }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(mailAllowed ? (theme.isDark ? theme.primaryAccent : .blue) : .secondary)
                        .frame(width: 42, height: 42)
                        .background(theme.isSignal ? AnyShapeStyle(Color.white.opacity(0.045)) : AnyShapeStyle(.thinMaterial), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    Spacer()
                    if appState.mailIsLoading {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "arrow.right.circle")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text(title)
                        .font(.headline)
                    Text(subtitle)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
            )
            .shadow(color: (theme.isDark ? theme.primaryAccent : .blue).opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .buttonStyle(.plain)
        .disabled(!mailAllowed || appState.mailIsLoading)
    }

    private func stat(_ progress: ScanProgress, _ key: String) -> String {
        progress.stats[key]?.description ?? ""
    }

    private var resultPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Letztes Ergebnis", systemImage: "doc.text.magnifyingglass")
                    .font(.title3.bold())
                Spacer()
                if appState.mailIsLoading {
                    Label("Jarvis prüft Mail", systemImage: "hourglass")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            Text(appState.mailResult)
                .font(.body)
                .lineSpacing(2)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .liquidGlassPanel(tint: .blue)
    }
}
