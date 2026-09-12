import SwiftUI

struct HealthView: View {
    @EnvironmentObject private var healthKit: HealthKitManager
    @State private var authorizationRequested = false
    @State private var authorizationError: String?

    var body: some View {
        Form {
            Section {
                Text("Jarvis liest deine Schlaf-, Puls- und Aktivitätswerte aus Apple Health (Apple Watch), damit er dich im Chat und über Automationen darauf ansprechen kann.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Section("Berechtigung") {
                Button("Zugriff auf Apple Health anfragen") {
                    Task {
                        do {
                            try await healthKit.requestAuthorization()
                            authorizationRequested = true
                            authorizationError = nil
                            await healthKit.sync()
                        } catch {
                            authorizationError = error.localizedDescription
                        }
                    }
                }
                if let authorizationError {
                    Label(authorizationError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .font(.callout)
                }
            }

            Section("Synchronisierung") {
                Button {
                    Task { await healthKit.sync() }
                } label: {
                    if healthKit.isSyncing {
                        ProgressView()
                    } else {
                        Text("Jetzt synchronisieren")
                    }
                }
                .disabled(healthKit.isSyncing)

                if let lastSyncedAt = healthKit.lastSyncedAt {
                    Label("Zuletzt synchronisiert: \(lastSyncedAt.formatted(date: .abbreviated, time: .shortened))", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .font(.callout)
                } else {
                    Label("Noch nicht synchronisiert.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .font(.callout)
                }

                if let lastError = healthKit.lastError {
                    Label(lastError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .font(.callout)
                }
            }

            Section {
                Text("Die Synchronisierung läuft automatisch, sobald diese App im Vordergrund ist - kein zuverlässiger Hintergrund-Sync in dieser Version.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Gesundheit")
    }
}

#Preview {
    NavigationStack { HealthView() }
        .environmentObject(HealthKitManager())
}
