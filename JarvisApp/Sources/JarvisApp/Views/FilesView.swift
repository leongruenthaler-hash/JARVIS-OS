import AppKit
import SwiftUI

struct FilesView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    @State private var pendingMoveTarget = ""
    @State private var showMoveConfirmation = false

    private let categories = [
        ("Rechnungen", "doc.text.fill"),
        ("Bewerbungen", "person.text.rectangle.fill"),
        ("Verträge", "signature"),
        ("Versicherungen", "shield.lefthalf.filled"),
        ("Fotos", "photo.fill"),
        ("Downloads", "arrow.down.circle.fill"),
        ("Sonstiges", "tray.full.fill")
    ]

    private var filesAllowed: Bool {
        appState.permissions["files"]?.allowed ?? false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionNotice
                progressSection
                searchPanel
                resultList
                actionGrid
                resultPanel
            }
            .padding(28)
            .frame(maxWidth: 1080, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Dateien")
        .alert("Dateien verschieben?", isPresented: $showMoveConfirmation) {
            Button("Abbrechen", role: .cancel) {}
            Button("Verschieben") {
                Task { await appState.moveCurrentFileSearchResults(to: pendingMoveTarget) }
            }
        } message: {
            Text("Jarvis verschiebt alle aktuellen Suchtreffer für \(appState.lastFileSearchQuery.isEmpty ? appState.fileSearchText : appState.lastFileSearchQuery) in den Ordner \(pendingMoveTarget) auf deinem Schreibtisch.")
        }
        .task {
            await appState.refreshPermissions()
            await appState.refreshScanStatesSafely()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "folder.fill.badge.gearshape", tint: .cyan)

            VStack(alignment: .leading, spacing: 7) {
                Text("Datei-Zentrale")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Scanne, finde und ordne lokale Dateien. Änderungen wie Verschieben bleiben bestätigungspflichtig, weil Chaos auf dem Schreibtisch schon genug Eigeninitiative hat.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .cyan)
    }

    @ViewBuilder
    private var permissionNotice: some View {
        HStack(spacing: 12) {
            Image(systemName: filesAllowed ? "checkmark.shield.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(filesAllowed ? .green : .orange)
                .font(.title3)
            VStack(alignment: .leading, spacing: 3) {
                Text(filesAllowed ? "Datei-Berechtigung aktiv" : "Datei-Berechtigung ist blockiert")
                    .font(.headline)
                Text(filesAllowed ? "Jarvis darf erlaubte lokale Ordner lesen. Verschieben, Kopieren oder Löschen wird vorher bestätigt." : "Aktiviere Dateien in der Datenschutz-Seite, bevor Jarvis lokale Ordner scannt oder Dateiaktionen vorbereitet.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if !filesAllowed {
                Button("Datenschutz öffnen") {
                    appState.selectedSection = .privacy
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .liquidGlassPanel(tint: filesAllowed ? .green : .orange)
    }

    private var progressSection: some View {
        ScanProgressCard(
            title: "Dateiindex",
            symbol: "folder.badge.gearshape",
            progress: appState.fileScanProgress,
            stats: [
                ("Wurzeln gefunden", stat("roots_found")),
                ("Wurzeln gescannt", stat("roots_scanned")),
                ("Dateien gefunden", stat("files_found")),
                ("Ordner gefunden", stat("folders_found")),
                ("Indexeinträge", stat("items_indexed")),
                ("Aktuell", stat("current_item")),
                ("Dateitypen", stat("top_extensions")),
                ("Letzter Lauf", stat("last_successful_scan")),
                ("Datenbankgröße", stat("database_bytes"))
            ]
        )
    }

    private var searchPanel: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Label("Dateien suchen", systemImage: "magnifyingglass")
                    .font(.title3.bold())
                Spacer()
                if appState.fileIsLoading {
                    ProgressView().controlSize(.small)
                }
            }

            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Zum Beispiel Rechnungen, Bewerbungen oder Verträge", text: $appState.fileSearchText)
                    .textFieldStyle(.plain)
                    .onSubmit { Task { await runSearch() } }
                Button {
                    Task { await runSearch() }
                } label: {
                    Label("Suchen", systemImage: "arrow.right.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!filesAllowed || appState.fileSearchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || appState.fileIsLoading)
            }
            .padding(13)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.22), lineWidth: 1)
            )

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(categories, id: \.0) { category in
                        Button {
                            Task { await runCategorySearch(category.0) }
                        } label: {
                            Label(category.0, systemImage: category.1)
                                .font(.callout.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(.thinMaterial, in: Capsule())
                                .overlay(Capsule().strokeBorder(Color.white.opacity(0.18), lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                        .disabled(!filesAllowed || appState.fileIsLoading)
                    }
                }
            }
        }
        .liquidGlassPanel(tint: .cyan)
    }

    @ViewBuilder
    private var resultList: some View {
        if !appState.fileSearchResults.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("\(appState.fileSearchResults.count) Treffer", systemImage: "list.bullet.rectangle.portrait")
                        .font(.title3.bold())
                    Spacer()
                    Button {
                        pendingMoveTarget = suggestedTargetFolder()
                        showMoveConfirmation = true
                    } label: {
                        Label("In Ordner verschieben", systemImage: "folder.badge.plus")
                    }
                    .buttonStyle(.bordered)
                    .disabled(!filesAllowed || appState.fileIsLoading)
                }

                LazyVStack(spacing: 10) {
                    ForEach(appState.fileSearchResults) { result in
                        fileResultRow(result)
                    }
                }
            }
            .liquidGlassPanel(tint: .blue)
        }
    }

    private func fileResultRow(_ result: FileSearchResult) -> some View {
        HStack(spacing: 12) {
            Image(systemName: result.isFolder ? "folder.fill" : "doc.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(result.isFolder ? .blue : .teal)
                .frame(width: 38, height: 38)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 13, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(result.name)
                    .font(.headline)
                    .lineLimit(1)
                Text("\(result.kindLabel) in \(result.locationLabel)")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            Button {
                reveal(result)
            } label: {
                Label("Finder", systemImage: "arrow.up.forward.app")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.bordered)
            .help("Im Finder anzeigen")
            .disabled(result.path.isEmpty)
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
        )
    }

    private var actionGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 14)], spacing: 14) {
            fileActionCard(
                title: "Dateiindex starten",
                subtitle: "Scannt erlaubte Ordner und speichert lokale Metadaten.",
                symbol: "play.circle.fill"
            ) {
                await appState.startFileIndexScan()
            }
            fileActionCard(
                title: "Index-Statistik",
                subtitle: "Aktualisiert Fortschritt, Einträge und Dateitypen.",
                symbol: "chart.bar.doc.horizontal"
            ) {
                await appState.refreshScanStatesSafely()
                appState.fileResult = "Dateiindex-Statistik aktualisiert."
            }
            fileActionCard(
                title: "Schreibtisch anzeigen",
                subtitle: "Lässt Jarvis deinen Schreibtisch zusammenfassen.",
                symbol: "macwindow.on.rectangle"
            ) {
                await appState.performFileCommand("Jarvis, was liegt auf meinem Schreibtisch?")
            }
            fileActionCard(
                title: "Bewerbungen ordnen",
                subtitle: "Sucht passende Dateien und zeigt sie vor dem Verschieben an.",
                symbol: "person.text.rectangle"
            ) {
                await runCategorySearch("Bewerbungen")
            }
            fileActionCard(
                title: "Rechnungen suchen",
                subtitle: "Sucht lokal nach Rechnungen, Belegen und Invoices.",
                symbol: "doc.text.viewfinder"
            ) {
                await runCategorySearch("Rechnungen")
            }
            fileActionCard(
                title: "Dateiindex zurücksetzen",
                subtitle: "Löscht nur den lokalen Metadatenindex, nicht deine Dateien.",
                symbol: "trash"
            ) {
                await appState.resetFileIndex()
            }
        }
    }

    private func fileActionCard(
        title: String,
        subtitle: String,
        symbol: String,
        action: @escaping () async -> Void
    ) -> some View {
        Button {
            Task { await action() }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(filesAllowed ? (theme.isDark ? theme.primaryAccent : .cyan) : .secondary)
                        .frame(width: 42, height: 42)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    Spacer()
                    if appState.fileIsLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.right.circle")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .buttonStyle(.plain)
        .disabled(!filesAllowed || appState.fileIsLoading)
    }

    private var resultPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Letztes Ergebnis", systemImage: "doc.text.magnifyingglass")
                .font(.title3.bold())
            Text(appState.fileResult)
                .font(.body)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private func runSearch() async {
        await appState.searchFilesInIndex(appState.fileSearchText)
    }

    private func runCategorySearch(_ category: String) async {
        appState.fileSearchText = category
        await appState.searchFilesInIndex(category)
    }

    private func suggestedTargetFolder() -> String {
        let query = (appState.lastFileSearchQuery.isEmpty ? appState.fileSearchText : appState.lastFileSearchQuery)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if categories.contains(where: { $0.0.caseInsensitiveCompare(query) == .orderedSame }) {
            return query
        }
        return query.isEmpty ? "Sortiert" : query
    }

    private func reveal(_ result: FileSearchResult) {
        guard !result.path.isEmpty else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: result.path)])
    }

    private func stat(_ key: String) -> String {
        appState.fileScanProgress.stats[key]?.description ?? ""
    }
}
