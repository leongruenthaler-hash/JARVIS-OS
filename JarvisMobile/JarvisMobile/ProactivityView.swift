import SwiftUI

struct ProactivityView: View {
    @State private var events: [ProactiveEvent] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    // Siehe ChatView.swift: RemoteSettings.isPaired ist nicht SwiftUI-reaktiv,
    // deshalb als @State + Refresh bei jedem Erscheinen des Tabs.
    @State private var isPaired = RemoteSettings.isPaired

    var body: some View {
        Group {
            if !isPaired {
                ContentUnavailableView(
                    "Noch nicht verbunden",
                    systemImage: "network.slash",
                    description: Text("Richte die Verbindung zum Mac Mini im Tab \"Verbindung\" ein.")
                )
            } else if events.isEmpty && !isLoading {
                ContentUnavailableView(
                    "Keine Hinweise",
                    systemImage: "bell.slash",
                    description: Text("Aktuell liegt nichts Neues von Jarvis vor.")
                )
            } else {
                List {
                    ForEach(events) { event in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(priorityLabel(event.priority))
                                    .font(.caption.weight(.semibold))
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(priorityColor(event.priority).opacity(0.18))
                                    .foregroundStyle(priorityColor(event.priority))
                                    .clipShape(Capsule())
                                Spacer()
                            }
                            Text(event.message)
                                .font(.body)
                            Text(event.reason)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                        .swipeActions(edge: .trailing) {
                            Button("Verwerfen", role: .destructive) {
                                Task { await dismiss(event) }
                            }
                            Button("Später") {
                                Task { await snooze(event) }
                            }
                            .tint(.orange)
                        }
                    }
                }
            }
        }
        .navigationTitle("Hinweise")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await refresh() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
        .onAppear { isPaired = RemoteSettings.isPaired }
        .task { await refresh() }
        .refreshable { await refresh() }
        .overlay {
            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding()
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
                    .padding()
            }
        }
    }

    private func refresh() async {
        guard RemoteSettings.isPaired else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            events = try await APIClient().proactivityEvents()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func dismiss(_ event: ProactiveEvent) async {
        do {
            try await APIClient().dismissProactivityEvent(dedupKey: event.dedupKey)
            events.removeAll { $0.id == event.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func snooze(_ event: ProactiveEvent) async {
        do {
            try await APIClient().snoozeProactivityEvent(dedupKey: event.dedupKey)
            events.removeAll { $0.id == event.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func priorityLabel(_ priority: String) -> String {
        switch priority {
        case "kritisch": return "Kritisch"
        case "wichtig": return "Wichtig"
        case "relevant": return "Relevant"
        default: return "Info"
        }
    }

    private func priorityColor(_ priority: String) -> Color {
        switch priority {
        case "kritisch": return .red
        case "wichtig": return .orange
        case "relevant": return .blue
        default: return .secondary
        }
    }
}

#Preview {
    NavigationStack { ProactivityView() }
}
