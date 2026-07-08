import SwiftUI

struct PhotosView: View {
    @EnvironmentObject private var appState: AppState
    @State private var photoSearchText = ""

    private var photosAllowed: Bool {
        appState.permissions["photos"]?.allowed ?? false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionNotice
                progressSection
                localVisionSection
                actionGrid
                searchSection
                resultPanel
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Fotos")
        .task {
            await appState.refreshPermissions()
            await appState.refreshPhotoPermissionStatus()
            await appState.refreshScanStatesSafely()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "photo.stack.fill", tint: .purple)

            VStack(alignment: .leading, spacing: 6) {
                Text("Fotoindex")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Jarvis scannt deine Fotos lokal, baut einen suchbaren Index auf und legt Treffer auf Wunsch in einem neuen Desktop-Ordner ab.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
            }
        }
        .liquidGlassPanel(tint: .purple)
    }

    @ViewBuilder
    private var permissionNotice: some View {
        HStack(spacing: 12) {
            Image(systemName: photosAllowed ? "checkmark.shield.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(photosAllowed ? .green : .orange)
                .font(.title3)
            VStack(alignment: .leading, spacing: 3) {
                Text(photosAllowed ? "Fotos-Berechtigung aktiv" : "Fotos-Berechtigung prüfen")
                    .font(.headline)
                Text("macOS-Status: \(appState.photoPermissionStatus). Jarvis nutzt den Fotos-Helper und speichert den Suchindex lokal.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Status prüfen") {
                Task { await appState.refreshPhotoPermissionStatus() }
            }
            .buttonStyle(.bordered)
        }
        .liquidGlassPanel(tint: photosAllowed ? .green : .orange)
    }

    private var progressSection: some View {
        ScanProgressCard(
            title: "Fotoindex",
            symbol: "photo.on.rectangle.angled",
            progress: appState.photoScanProgress,
            stats: [
                ("Fotos gefunden", stat("photos_found")),
                ("Fotos indexiert", stat("photos_indexed")),
                ("Videos", stat("videos_found")),
                ("Labels erkannt", stat("labels_recognized")),
                ("Aktuell", stat("current_photo")),
                ("Letzter Lauf", stat("last_successful_scan")),
                ("Datenbankgröße", stat("database_bytes"))
            ]
        )
    }

    private var actionGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 14)], spacing: 14) {
            photoActionCard("Freigabe prüfen", "Liest den aktuellen macOS-Fotos-Status.", "checkmark.shield") {
                await appState.refreshPhotoPermissionStatus()
            }
            photoActionCard("Freigabe anfordern", "Öffnet den Fotos-Freigabeprozess.", "hand.raised.fill") {
                await appState.requestPhotoPermission()
            }
            photoActionCard("Fotoindex starten", "Scannt Fotos und Videos und speichert den Index lokal.", "play.circle.fill") {
                await appState.startPhotoIndexScan()
            }
            photoActionCard("Vision-Modell prüfen", "Prüft lokal, ob Ollama ein Vision-Modell bereitstellt.", "eye.circle") {
                await appState.refreshLocalVisionStatus()
            }
            photoActionCard("Fotos lokal analysieren", "Ergänzt lokale KI-Beschreibungen ohne OpenAI-Upload.", "sparkles.rectangle.stack") {
                await appState.startLocalPhotoVisionAnalysis()
            }
            photoActionCard("Analyse pausieren", "Pausieren ist vorbereitet. Laufende lokale Jobs enden aktuell nach dem nächsten Bild.", "pause.circle") {
                appState.photoResult = "Pausieren ist vorbereitet. Aktuell beendet Jarvis laufende Analysejobs sauber nach dem nächsten Bild."
            }
            photoActionCard("Analyse fortsetzen", "Startet die lokale Analyse erneut und überspringt bereits analysierte Fotos.", "playpause.circle") {
                await appState.startLocalPhotoVisionAnalysis()
            }
            photoActionCard("Hintergrundscan starten", "Startet den Indexlauf im Hintergrundpfad des Core.", "clock.arrow.2.circlepath") {
                await appState.startPhotoBackgroundScan()
            }
            photoActionCard("KI-Beschreibungen löschen", "Löscht nur lokale Vision-Beschreibungen, nicht deine Fotos.", "eraser") {
                await appState.resetLocalPhotoVisionDescriptions()
            }
            photoActionCard("Suche: Auto", "Testet die lokale Suche nach Auto/Fahrzeug.", "car.fill") {
                await appState.performPhotoCommand("Jarvis, zeig mir Bilder mit Autos.")
            }
            photoActionCard("Suche: Schreibtisch", "Testet die lokale Suche nach Schreibtisch.", "desktopcomputer") {
                await appState.performPhotoCommand("Jarvis, zeig mir Fotos mit meinem Schreibtisch.")
            }
            photoActionCard("Index-Statistik", "Aktualisiert die sichtbaren Indexdaten.", "chart.bar.doc.horizontal") {
                await appState.refreshScanStatesSafely()
                appState.photoResult = "Index-Statistik aktualisiert."
            }
            photoActionCard("Fotoindex zurücksetzen", "Löscht den lokalen Fotoindex. Deine Fotos bleiben natürlich unangetastet.", "trash") {
                await appState.resetPhotoIndex()
            }
        }
    }

    private func photoActionCard(
        _ title: String,
        _ subtitle: String,
        _ symbol: String,
        action: @escaping () async -> Void
    ) -> some View {
        Button {
            Task { await action() }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(.purple)
                        .frame(width: 42, height: 42)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    Spacer()
                    if appState.photoIsLoading {
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
            .shadow(color: Color.purple.opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .buttonStyle(.plain)
        .disabled(appState.photoIsLoading)
    }

    private var resultPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Letztes Ergebnis", systemImage: "doc.text.magnifyingglass")
                .font(.title3.bold())
            Text(appState.photoResult)
                .font(.body)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .liquidGlassPanel(tint: .purple)
    }

    private func stat(_ key: String) -> String {
        appState.photoScanProgress.stats[key]?.description ?? ""
    }

    private var searchSection: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField("Fotos suchen ...", text: $photoSearchText)
                .textFieldStyle(.plain)
                .onSubmit {
                    Task { await runPhotoSearch() }
                }
            Button {
                Task { await runPhotoSearch() }
            } label: {
                Label("Suchen", systemImage: "arrow.right.circle.fill")
            }
            .disabled(photoSearchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || appState.photoIsLoading)
        }
        .padding(12)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
        )
    }

    private func runPhotoSearch() async {
        let query = photoSearchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        await appState.performPhotoCommand("Jarvis, zeig mir Fotos mit \(query).")
    }

    private var localVisionSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: appState.localVisionStatus.available ? "eye.fill" : "eye.slash.fill")
                    .foregroundStyle(appState.localVisionStatus.available ? .green : .orange)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Lokale Vision")
                        .font(.headline)
                    Text(appState.localVisionStatus.message)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if !appState.localVisionStatus.model.isEmpty {
                    Text(appState.localVisionStatus.model)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.purple.opacity(0.14), in: Capsule())
                }
            }

            ScanProgressCard(
                title: "Lokale Fotoanalyse",
                symbol: "eye.trianglebadge.exclamationmark",
                progress: appState.photoVisionProgress,
                stats: [
                    ("Modell", visionStat("model")),
                    ("Modell bereit", visionStat("model_available")),
                    ("Analysiert", visionStat("analyzed")),
                    ("Offen", visionStat("pending")),
                    ("Beschreibungen", visionStat("local_descriptions")),
                    ("Fehler", visionStat("errors")),
                    ("Aktuell", visionStat("current_photo")),
                    ("Letzter Lauf", visionStat("last_successful_scan"))
                ]
            )

            Text("Datenschutz: Diese Analyse läuft nur lokal über Ollama. Jarvis lädt keine Bilder zu OpenAI oder in eine Cloud hoch und identifiziert keine unbekannten Personen namentlich.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .liquidGlassPanel(tint: .purple)
    }

    private func visionStat(_ key: String) -> String {
        appState.photoVisionProgress.stats[key]?.description ?? ""
    }
}
