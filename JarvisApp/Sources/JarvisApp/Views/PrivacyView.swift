import SwiftUI

struct PrivacyView: View {
    @EnvironmentObject private var appState: AppState
    @State private var showDeleteHistoryConfirmation = false
    @State private var showClearLogsConfirmation = false

    private let groups: [PermissionGroup] = [
        PermissionGroup(title: "Eingabe & Geräte", symbol: "mic", permissions: ["microphone", "camera", "location"]),
        PermissionGroup(title: "Apple Apps", symbol: "apple.logo", permissions: ["mail", "calendar", "reminders", "contacts", "notes", "photos", "music"]),
        PermissionGroup(title: "Dateien & Internet", symbol: "folder", permissions: ["files", "internet", "external_api"]),
        PermissionGroup(title: "KI & Speicher", symbol: "brain.head.profile", permissions: ["cloud_llm", "memory"])
    ]

    private var activeCount: Int {
        appState.permissions.values.filter(\.allowed).count
    }

    private var totalCount: Int {
        appState.permissions.count
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                summaryGrid
                permissionGroups
                dataActions
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Datenschutz")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshPermissions() }
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await appState.refreshPermissions() }
        .confirmationDialog("Verlauf löschen?", isPresented: $showDeleteHistoryConfirmation, titleVisibility: .visible) {
            Button("Verlauf löschen", role: .destructive) {
                Task { await appState.deleteHistory() }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Jarvis löscht Gesprächsverlauf und Hintergrund-Cache. Berechtigungen bleiben erhalten.")
        }
        .confirmationDialog("Technische Logs löschen?", isPresented: $showClearLogsConfirmation, titleVisibility: .visible) {
            Button("Logs löschen", role: .destructive) {
                Task { await appState.clearLogs() }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Jarvis löscht technische Logs. Sensible Inhalte sollten dort ohnehin nicht stehen.")
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "hand.raised.fill", tint: .green)

            VStack(alignment: .leading, spacing: 6) {
                Text("Datenschutz-Zentrale")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Hier steuerst du, worauf Jarvis zugreifen darf. Jede Berechtigung ist einzeln schaltbar und kritische Aktionen bleiben bestätigungspflichtig.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .liquidGlassPanel(tint: .green)
    }

    private var summaryGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 14)], spacing: 14) {
            summaryCard(
                title: "Aktive Berechtigungen",
                value: "\(activeCount) von \(max(totalCount, 1))",
                symbol: "checkmark.shield.fill",
                tint: .green
            )
            summaryCard(
                title: "KI-Modus",
                value: appState.modelStatus.openAIEnabled ? "Cloud aktiv" : "Lokal aktiv",
                symbol: appState.modelStatus.openAIEnabled ? "cloud.fill" : "house.fill",
                tint: appState.modelStatus.openAIEnabled ? .orange : .blue
            )
            summaryCard(
                title: "OpenAI Key",
                value: appState.modelStatus.openAIKeyPresent ? "Keychain" : "Nicht gesetzt",
                symbol: appState.modelStatus.openAIKeyPresent ? "key.fill" : "key.slash.fill",
                tint: appState.modelStatus.openAIKeyPresent ? .green : .secondary
            )
            summaryCard(
                title: "Logging",
                value: "Inhaltsarm",
                symbol: "doc.text.magnifyingglass",
                tint: .purple
            )
        }
    }

    private func summaryCard(title: String, value: String, symbol: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 34, height: 34)
                .background(.thinMaterial, in: Circle())

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

    private var permissionGroups: some View {
        VStack(alignment: .leading, spacing: 16) {
            sectionHeader("Berechtigungen", subtitle: "Wenn ein Schalter aus ist, soll Jarvis diesen Bereich nicht eigenständig nutzen.")

            ForEach(groups) { group in
                VStack(alignment: .leading, spacing: 12) {
                    Label(group.title, systemImage: group.symbol)
                        .font(.title3.bold())

                    VStack(spacing: 10) {
                        ForEach(group.permissions, id: \.self) { permission in
                            permissionRow(permission)
                        }
                    }
                }
                .liquidGlassPanel(tint: .green)
            }
        }
    }

    private func permissionRow(_ permission: String) -> some View {
        let info = appState.permissions[permission]
        let allowed = info?.allowed ?? false

        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: permissionSymbol(permission))
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(allowed ? .green : .secondary)
                .frame(width: 34, height: 34)
                .background(.thinMaterial, in: Circle())
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(permissionTitle(permission))
                        .font(.headline)
                    statusPill(allowed: allowed)
                }
                Text(info?.explanation ?? fallbackExplanation(permission))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let updated = info?.updatedAt, !updated.isEmpty {
                    Text("Zuletzt geändert: \(updated)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer(minLength: 12)

            Toggle("", isOn: Binding(
                get: { appState.permissions[permission]?.allowed ?? false },
                set: { newValue in
                    DispatchQueue.main.async {
                        Task { await appState.setPermission(permission, allowed: newValue) }
                    }
                }
            ))
            .toggleStyle(.switch)
            .labelsHidden()
        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private var dataActions: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Daten verwalten", subtitle: "Exportieren oder löschen, ohne im Terminal herumzustochern.")

            HStack(spacing: 10) {
                Button {
                    Task { await appState.exportPrivacyData() }
                } label: {
                    Label("Datenschutzdaten exportieren", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(.borderedProminent)

                Button(role: .destructive) {
                    showDeleteHistoryConfirmation = true
                } label: {
                    Label("Verlauf löschen", systemImage: "trash")
                }
                .buttonStyle(.bordered)

                Button(role: .destructive) {
                    showClearLogsConfirmation = true
                } label: {
                    Label("Logs löschen", systemImage: "xmark.bin")
                }
                .buttonStyle(.bordered)
            }
        }
        .liquidGlassPanel(tint: .green)
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

    private func statusPill(allowed: Bool) -> some View {
        Text(allowed ? "Erlaubt" : "Blockiert")
            .font(.caption.weight(.semibold))
            .foregroundStyle(allowed ? .green : .secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background((allowed ? Color.green : Color.secondary).opacity(0.12), in: Capsule())
    }

    private func permissionTitle(_ permission: String) -> String {
        switch permission {
        case "microphone": return "Mikrofon"
        case "camera": return "Kamera"
        case "location": return "Standort"
        case "mail": return "Mail"
        case "calendar": return "Kalender"
        case "reminders": return "Erinnerungen"
        case "contacts": return "Kontakte"
        case "notes": return "Notizen"
        case "files": return "Dateien"
        case "photos": return "Fotos"
        case "music": return "Musik"
        case "internet": return "Internet"
        case "external_api": return "Externe APIs"
        case "cloud_llm": return "Cloud-KI"
        case "memory": return "Memory"
        default: return permission
        }
    }

    private func permissionSymbol(_ permission: String) -> String {
        switch permission {
        case "microphone": return "mic.fill"
        case "camera": return "camera.fill"
        case "location": return "location.fill"
        case "mail": return "envelope.fill"
        case "calendar": return "calendar"
        case "reminders": return "checklist"
        case "contacts": return "person.crop.circle.fill"
        case "notes": return "note.text"
        case "files": return "folder.fill"
        case "photos": return "photo.fill.on.rectangle.fill"
        case "music": return "music.note"
        case "internet": return "network"
        case "external_api": return "point.3.connected.trianglepath.dotted"
        case "cloud_llm": return "cloud.fill"
        case "memory": return "brain.head.profile"
        default: return "switch.2"
        }
    }

    private func fallbackExplanation(_ permission: String) -> String {
        "Jarvis nutzt diese Berechtigung nur, wenn du eine passende Funktion aktiv verwendest."
    }
}

private struct PermissionGroup: Identifiable {
    let title: String
    let symbol: String
    let permissions: [String]

    var id: String { title }
}
