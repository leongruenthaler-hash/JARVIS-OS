import SwiftUI

struct MailView: View {
    @EnvironmentObject private var appState: AppState

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
                title: "Hintergrundscan starten",
                subtitle: "Bereitet ein Mail-Update im Hintergrund vor.",
                symbol: "moon.stars.fill",
                command: "Jarvis, scanne meine Mails im Hintergrund.",
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

            ScanProgressCard(
                title: "Mail-Hintergrundscan",
                symbol: "clock.arrow.2.circlepath",
                progress: appState.mailBackgroundProgress,
                stats: [
                    ("Status", stat(appState.mailBackgroundProgress, "background_active")),
                    ("Letzter Scan", stat(appState.mailBackgroundProgress, "last_scan")),
                    ("Nächste Aktualisierung", stat(appState.mailBackgroundProgress, "next_update")),
                    ("Neue Mails", stat(appState.mailBackgroundProgress, "new_mails")),
                    ("Indexierte Mails", stat(appState.mailBackgroundProgress, "mails_indexed")),
                    ("Fehler", stat(appState.mailBackgroundProgress, "last_error"))
                ]
            )
        }
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
                        .foregroundStyle(mailAllowed ? .blue : .secondary)
                        .frame(width: 42, height: 42)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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
            .shadow(color: Color.blue.opacity(0.08), radius: 18, x: 0, y: 10)
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
