import SwiftUI

/// Phase B: lets the user see, search, correct and delete what Jarvis has actually
/// remembered about them - the counterpart to the auto-extraction/Context Engine on
/// the Python side (app/memory.py, app/core/context_engine.py). Before this existed,
/// long_memory.json was only inspectable by opening the raw file.
struct MemoryView: View {
    @EnvironmentObject private var appState: AppState
    @State private var searchText = ""
    @State private var selectedCategory = ""
    @State private var factPendingDeletion: MemoryFact?

    private var categories: [String] {
        Array(Set(appState.memoryFacts.map(\.category))).sorted()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                filterBar
                factList
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Gedächtnis")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshMemoryFacts(search: searchText, category: selectedCategory) }
                } label: {
                    Label("Aktualisieren", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await appState.refreshMemoryFacts() }
        .confirmationDialog("Erinnerung löschen?", isPresented: Binding(
            get: { factPendingDeletion != nil },
            set: { if !$0 { factPendingDeletion = nil } }
        ), titleVisibility: .visible) {
            Button("Löschen", role: .destructive) {
                if let fact = factPendingDeletion {
                    Task { await appState.deleteMemoryFact(fact) }
                }
                factPendingDeletion = nil
            }
            Button("Abbrechen", role: .cancel) { factPendingDeletion = nil }
        } message: {
            Text("Diese Erinnerung wird endgültig entfernt und danach nicht mehr im Gespräch verwendet.")
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "brain.head.profile", tint: .purple)

            VStack(alignment: .leading, spacing: 6) {
                Text("Gedächtnis")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Was Jarvis sich dauerhaft über dich gemerkt hat. Du kannst jede Erinnerung ansehen, bestätigen, ablehnen oder löschen - nichts davon ist versteckt.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                Text("\(appState.memoryFactsTotal) gespeicherte Erinnerung(en)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
        }
        .liquidGlassPanel(tint: .purple)
    }

    private var filterBar: some View {
        HStack(spacing: 10) {
            TextField("Erinnerungen durchsuchen ...", text: $searchText)
                .textFieldStyle(.roundedBorder)
                .onSubmit {
                    Task { await appState.refreshMemoryFacts(search: searchText, category: selectedCategory) }
                }

            Picker("Kategorie", selection: $selectedCategory) {
                Text("Alle Kategorien").tag("")
                ForEach(categories, id: \.self) { category in
                    Text(category).tag(category)
                }
            }
            .frame(maxWidth: 220)
            .onChange(of: selectedCategory) { _, newValue in
                Task { await appState.refreshMemoryFacts(search: searchText, category: newValue) }
            }
        }
    }

    @ViewBuilder
    private var factList: some View {
        if appState.memoryIsLoading && appState.memoryFacts.isEmpty {
            ProgressView("Lade Erinnerungen ...")
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(40)
        } else if appState.memoryFacts.isEmpty {
            Text("Noch keine Erinnerungen gespeichert.")
                .foregroundStyle(.secondary)
                .padding(40)
        } else {
            VStack(spacing: 10) {
                ForEach(appState.memoryFacts) { fact in
                    factRow(fact)
                }
            }
        }
    }

    private func factRow(_ fact: MemoryFact) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(fact.content)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 6) {
                        pill(fact.category, tint: .blue)
                        pill(sensitivityLabel(fact.sensitivity), tint: sensitivityTint(fact.sensitivity))
                        pill(statusLabel(fact.status), tint: statusTint(fact.status))
                        if let lastUsed = fact.lastUsedAt, !lastUsed.isEmpty {
                            Text("Zuletzt verwendet: \(lastUsed)")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                }
                Spacer(minLength: 12)
            }

            HStack(spacing: 8) {
                if fact.status != "confirmed" {
                    Button("Bestätigen") {
                        Task { await appState.confirmMemoryFact(fact) }
                    }
                    .buttonStyle(.bordered)
                }
                if fact.status != "rejected" {
                    Button("Ablehnen") {
                        Task { await appState.rejectMemoryFact(fact) }
                    }
                    .buttonStyle(.bordered)
                }
                Button("Löschen", role: .destructive) {
                    factPendingDeletion = fact
                }
                .buttonStyle(.bordered)
                Spacer()
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

    private func sensitivityLabel(_ sensitivity: String) -> String {
        switch sensitivity {
        case "personal": return "Persönlich"
        case "confidential": return "Vertraulich"
        case "highly-sensitive": return "Hochsensibel"
        default: return "Normal"
        }
    }

    private func sensitivityTint(_ sensitivity: String) -> Color {
        switch sensitivity {
        case "personal": return .orange
        case "confidential": return .red
        case "highly-sensitive": return .red
        default: return .secondary
        }
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "pending_confirmation": return "Wartet auf Bestätigung"
        case "rejected": return "Abgelehnt"
        default: return "Bestätigt"
        }
    }

    private func statusTint(_ status: String) -> Color {
        switch status {
        case "pending_confirmation": return .yellow
        case "rejected": return .secondary
        default: return .green
        }
    }
}
