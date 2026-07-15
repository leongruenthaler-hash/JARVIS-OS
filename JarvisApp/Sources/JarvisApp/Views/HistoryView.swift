import SwiftUI

struct HistoryView: View {
    @EnvironmentObject private var appState: AppState

    private var groupedByDay: [ConversationHistoryDayGroup] {
        let grouped = Dictionary(grouping: appState.conversationHistory.turns) { turn in
            String(turn.createdAt.prefix(10))
        }
        return grouped.keys.sorted(by: >).map { day in
            ConversationHistoryDayGroup(day: day, turns: grouped[day] ?? [])
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if appState.conversationHistoryLoading {
                    ProgressView("Verlauf wird geladen ...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if !appState.conversationHistory.recordingEnabled {
                    disabledState
                } else if appState.conversationHistory.turns.isEmpty {
                    emptyState
                } else {
                    dayList
                }
            }
            .navigationTitle("Verlauf")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        Task { await appState.refreshConversationHistory() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .help("Verlauf aktualisieren")
                }
            }
        }
        .background(LiquidGlassBackground())
        .task {
            await appState.refreshConversationHistory()
        }
    }

    private var disabledState: some View {
        placeholderLayout(
            symbol: "clock.arrow.circlepath",
            title: "Verlauf",
            message: "Verlaufsspeicherung ist aus. Aktivier sie in den Einstellungen, um hier deine letzten Gespräche zu sehen."
        ) {
            Button {
                appState.selectedSection = .settings
            } label: {
                Label("Zu den Einstellungen", systemImage: "gearshape")
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var emptyState: some View {
        placeholderLayout(
            symbol: "clock.arrow.circlepath",
            title: "Verlauf",
            message: "Noch keine Gespräche aufgezeichnet. Sobald du mit Jarvis sprichst oder schreibst, erscheinen sie hier."
        ) {
            EmptyView()
        }
    }

    private func placeholderLayout<Extra: View>(
        symbol: String,
        title: String,
        message: String,
        @ViewBuilder extra: () -> Extra
    ) -> some View {
        VStack(spacing: 22) {
            LiquidGlassIcon(symbol: symbol, tint: .cyan)
                .scaleEffect(1.18)
            VStack(spacing: 8) {
                Text(title)
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text(message)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 560)
            }
            extra()
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var dayList: some View {
        List(groupedByDay) { group in
            NavigationLink(value: group) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(formattedDay(group.day))
                        .font(.headline)
                    Text("\(group.turns.count) Nachrichten")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            }
        }
        .listStyle(.inset)
        .navigationDestination(for: ConversationHistoryDayGroup.self) { group in
            HistoryDayDetailView(group: group, formattedDay: formattedDay(group.day))
        }
    }

    private func formattedDay(_ day: String) -> String {
        let inputFormatter = DateFormatter()
        inputFormatter.dateFormat = "yyyy-MM-dd"
        guard let date = inputFormatter.date(from: day) else { return day }
        let outputFormatter = DateFormatter()
        outputFormatter.dateStyle = .full
        outputFormatter.locale = Locale(identifier: "de_DE")
        return outputFormatter.string(from: date)
    }
}

struct ConversationHistoryDayGroup: Identifiable, Hashable {
    let day: String
    let turns: [ConversationTurnPayload]

    var id: String { day }

    static func == (lhs: ConversationHistoryDayGroup, rhs: ConversationHistoryDayGroup) -> Bool {
        lhs.day == rhs.day
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(day)
    }
}

private struct HistoryDayDetailView: View {
    let group: ConversationHistoryDayGroup
    let formattedDay: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(group.turns) { turn in
                    HistoryTurnRow(turn: turn)
                }
            }
            .padding(24)
            .frame(maxWidth: 720, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle(formattedDay)
    }
}

private struct HistoryTurnRow: View {
    let turn: ConversationTurnPayload

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: turn.role == "user" ? "person.fill" : "sparkles")
                .foregroundStyle(turn.role == "user" ? .blue : .cyan)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 3) {
                Text(turn.role == "user" ? "Du" : "Jarvis")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(turn.content)
                    .font(.body)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        )
    }
}
