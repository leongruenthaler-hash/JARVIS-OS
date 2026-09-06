import SwiftUI

struct ChatView: View {
    @State private var messages: [ChatMessage] = []
    @State private var draft = ""
    @State private var isSending = false
    @State private var errorMessage: String?
    // RemoteSettings.isPaired liest UserDefaults/Keychain direkt - ohne dieses
    // @State wuerde SwiftUI diese View nie neu zeichnen, wenn die Kopplung im
    // "Verbindung"-Tab erst NACH dem ersten Anzeigen dieses Tabs gesetzt wird
    // (Live-Bug 2026-09-06: Chat blieb dauerhaft auf "Noch nicht verbunden"
    // stehen, obwohl der Verbindungstest schon erfolgreich war).
    @State private var isPaired = RemoteSettings.isPaired

    var body: some View {
        VStack(spacing: 0) {
            if !isPaired {
                ContentUnavailableView(
                    "Noch nicht verbunden",
                    systemImage: "network.slash",
                    description: Text("Richte die Verbindung zum Mac Mini im Tab \"Verbindung\" ein.")
                )
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(messages) { message in
                                ChatBubble(message: message)
                                    .id(message.id)
                            }
                        }
                        .padding()
                    }
                    .onChange(of: messages.count) { _, _ in
                        if let last = messages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                HStack(spacing: 8) {
                    TextField("Nachricht an Jarvis", text: $draft, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(1...4)
                    Button {
                        Task { await send() }
                    } label: {
                        if isSending {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.title2)
                        }
                    }
                    .disabled(isSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding()
            }
        }
        .navigationTitle("Chat")
        .onAppear { isPaired = RemoteSettings.isPaired }
    }

    private func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        errorMessage = nil
        messages.append(ChatMessage(role: "user", content: text))
        isSending = true
        defer { isSending = false }

        let history = messages.map { ["role": $0.role, "content": $0.content] }
        do {
            let response = try await APIClient().sendChat(text, history: history)
            messages.append(ChatMessage(role: "assistant", content: response.answer))
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == "user" { Spacer(minLength: 40) }
            Text(message.content)
                .padding(12)
                .background(message.role == "user" ? Color.accentColor : Color(.secondarySystemBackground))
                .foregroundStyle(message.role == "user" ? .white : .primary)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            if message.role != "user" { Spacer(minLength: 40) }
        }
    }
}

#Preview {
    NavigationStack { ChatView() }
}
