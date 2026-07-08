import SwiftUI

struct CalendarWorkspaceView: View {
    @EnvironmentObject private var appState: AppState

    private var calendarAllowed: Bool {
        appState.permissions["calendar"]?.allowed ?? false
    }

    private var remindersAllowed: Bool {
        appState.permissions["reminders"]?.allowed ?? false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionNotice
                statusCards
                quickActions
                recentActivity
                guidancePanel
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Kalender")
        .task {
            await appState.refreshPermissions()
            await appState.refreshCalendarOverview()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "calendar.badge.clock", tint: .indigo)

            VStack(alignment: .leading, spacing: 6) {
                Text("Kalender & Erinnerungen")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Jarvis kann Termine und Erinnerungen anlegen, prüfen und auf Wunsch auch aus Mail-Kontext ableiten. Die eigentliche Aktion bleibt aber immer transparent.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
            }
        }
        .liquidGlassPanel(tint: .indigo)
    }

    @ViewBuilder
    private var permissionNotice: some View {
        HStack(spacing: 12) {
            Image(systemName: calendarAllowed || remindersAllowed ? "checkmark.shield.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(calendarAllowed || remindersAllowed ? .green : .orange)
                .font(.title3)
            VStack(alignment: .leading, spacing: 3) {
                Text(calendarAllowed || remindersAllowed ? "Berechtigungen bereit" : "Berechtigungen prüfen")
                    .font(.headline)
                Text(permissionText)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Datenschutz öffnen") {
                appState.selectedSection = .privacy
            }
            .buttonStyle(.borderedProminent)
        }
        .liquidGlassPanel(tint: calendarAllowed || remindersAllowed ? .green : .orange)
    }

    private var statusCards: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 14)], spacing: 14) {
            statusCard(
                title: "Kalender",
                subtitle: calendarAllowed ? "Kalenderzugriff aktiv" : "Kalenderzugriff blockiert",
                symbol: "calendar",
                tint: calendarAllowed ? .green : .orange,
                details: [
                    ("Status", permissionLabel("calendar")),
                    ("Nächster Termin", firstCalendarTitle()),
                    ("Modus", appState.modelStatus.provider.lowercased() == "openai" ? "Cloud nur bei Zustimmung" : "Lokal zuerst")
                ]
            )
            statusCard(
                title: "Erinnerungen",
                subtitle: remindersAllowed ? "Erinnerungenzugriff aktiv" : "Erinnerungenzugriff blockiert",
                symbol: "checklist",
                tint: remindersAllowed ? .green : .orange,
                details: [
                    ("Status", permissionLabel("reminders")),
                    ("Nächste Erinnerung", firstReminderTitle()),
                    ("Lösung", "Jarvis fragt vor kritischen Aktionen nach")
                ]
            )
            statusCard(
                title: "Automatik",
                subtitle: appState.privacySummary,
                symbol: "sparkles",
                tint: .indigo,
                details: [
                    ("Auto aus Mail", boolLabel("auto_calendar_from_mail_enabled")),
                    ("Termine geladen", "\(appState.calendarOverview.calendar.count)"),
                    ("Erinnerungen geladen", "\(appState.calendarOverview.reminders.count)"),
                    ("Inhalte lokal", "Ja"),
                    ("Bestätigung", "Vor kritischen Aktionen")
                ]
            )
        }
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Schnellaktionen", subtitle: "So testest du Kalender und Erinnerungen ohne Umwege.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 14)], spacing: 14) {
                actionCard(
                    title: "Heute anzeigen",
                    subtitle: "Jarvis fasst den heutigen Kalender und offene Erinnerungen zusammen.",
                    symbol: "calendar.day.timeline.left",
                    command: "Jarvis, was steht heute an?"
                )
                actionCard(
                    title: "Nächste Termine",
                    subtitle: "Fragt nach den nächsten anstehenden Terminen.",
                    symbol: "calendar.badge.clock",
                    command: "Jarvis, was sind meine nächsten Termine?"
                )
                actionCard(
                    title: "Neue Erinnerung",
                    subtitle: "Testet das Anlegen einer Erinnerung per Sprache.",
                    symbol: "bell.badge.fill",
                    command: "Jarvis, erstelle morgen um 18 Uhr eine Erinnerung, dass ich Codex weiter teste."
                )
                actionCard(
                    title: "Neuer Termin",
                    subtitle: "Testet das Anlegen eines Kalendereintrags per Sprache.",
                    symbol: "plus.circle.fill",
                    command: "Jarvis, erstelle morgen um 14 Uhr einen Kalendereintrag für einen Testtermin."
                )
                actionCard(
                    title: "Automatik prüfen",
                    subtitle: "Fragt Jarvis direkt nach dem Status der Mail-zu-Kalender-Automatik.",
                    symbol: "arrow.triangle.branch",
                    command: "Jarvis, ist die automatische Kalender- und Erinnerungslogik aktiv?"
                )
                actionCard(
                    title: "Hinweise",
                    subtitle: "Jarvis erklärt dir kurz, welche Berechtigungen noch fehlen.",
                    symbol: "info.circle.fill",
                    command: "Jarvis, welche Berechtigung fehlt dir für Kalender und Erinnerungen?"
                )
            }
        }
    }

    private var recentActivity: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Letzte Aktivität", subtitle: "Die letzten Kalender- und Erinnerungs-Sätze aus dem Chat.")

            let relevantMessages = appState.messages.reversed().filter { message in
                let text = message.text.lowercased()
                return text.contains("kalender") || text.contains("termin") || text.contains("erinner")
            }.prefix(5)

            if relevantMessages.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    placeholderCard(
                        title: "Keine Chat-Aktivität",
                        subtitle: "Unten stehen die geladenen Kern-Daten aus Kalender und Erinnerungen."
                    )
                    if !appState.calendarOverview.calendar.items.isEmpty || !appState.calendarOverview.reminders.items.isEmpty {
                        liveDataPanel
                    }
                }
            } else {
                VStack(spacing: 10) {
                    ForEach(Array(relevantMessages), id: \.id) { message in
                        activityRow(message)
                    }
                }
                if !appState.calendarOverview.calendar.items.isEmpty || !appState.calendarOverview.reminders.items.isEmpty {
                    liveDataPanel
                }
            }
        }
    }

    private var liveDataPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !appState.calendarOverview.calendar.items.isEmpty {
                Text("Nächste Termine")
                    .font(.headline)
                VStack(spacing: 10) {
                    ForEach(appState.calendarOverview.calendar.items.prefix(3)) { item in
                        overviewRow(
                            icon: "calendar",
                            title: item.title,
                            detail: item.start ?? item.end ?? "",
                            tint: .indigo
                        )
                    }
                }
            }

            if !appState.calendarOverview.reminders.items.isEmpty {
                Text("Offene Erinnerungen")
                    .font(.headline)
                VStack(spacing: 10) {
                    ForEach(appState.calendarOverview.reminders.items.prefix(3)) { item in
                        overviewRow(
                            icon: "bell",
                            title: item.title,
                            detail: item.due ?? "",
                            tint: .green
                        )
                    }
                }
            }
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var guidancePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeader("Worauf Jarvis reagiert", subtitle: "Du musst ihn nicht technisch ansprechen. Normale Sprache reicht.")
            Text("• „Erstelle morgen um 18 Uhr eine Erinnerung, dass ich Codex weiter teste.“\n• „Zeig mir meine Termine für heute.“\n• „Ist die Kalender-Automatik aktiv?“\n• „Was fehlt dir für Erinnerungen?“")
                .foregroundStyle(.secondary)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .liquidGlassPanel(tint: .indigo)
    }

    private func actionCard(title: String, subtitle: String, symbol: String, command: String) -> some View {
        Button {
            Task { await appState.send(command) }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(.indigo)
                        .frame(width: 42, height: 42)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    Spacer()
                    Image(systemName: "arrow.right.circle")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 146, alignment: .topLeading)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
            )
            .shadow(color: Color.indigo.opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .buttonStyle(.plain)
    }

    private func statusCard(title: String, subtitle: String, symbol: String, tint: Color, details: [(String, String)]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: symbol)
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 42, height: 42)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                Spacer()
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .foregroundStyle(.secondary)
                    .font(.callout)
            }

            VStack(alignment: .leading, spacing: 8) {
                ForEach(details.indices, id: \.self) { index in
                    let item = details[index]
                    HStack(alignment: .top, spacing: 10) {
                        Text(item.0)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .frame(width: 90, alignment: .leading)
                        Text(item.1)
                            .font(.callout)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                }
            }
            .padding(12)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 190, alignment: .topLeading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
        )
    }

    private func placeholderCard(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.headline)
            Text(subtitle)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private func activityRow(_ message: ChatMessage) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(message.role == .jarvis ? Color.indigo.opacity(0.85) : Color.secondary.opacity(0.35))
                .frame(width: 10, height: 10)
                .padding(.top, 7)
            VStack(alignment: .leading, spacing: 4) {
                Text(message.role == .jarvis ? "Jarvis" : message.role == .system ? "System" : appState.displayUserName)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(message.text)
                    .font(.body)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private func sectionHeader(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title2.weight(.bold))
            Text(subtitle)
                .foregroundStyle(.secondary)
        }
    }

    private var permissionText: String {
        switch (calendarAllowed, remindersAllowed) {
        case (true, true):
            return "Kalender und Erinnerungen sind aktiv. Jarvis darf nach Bestätigung arbeiten."
        case (true, false):
            return "Kalender ist aktiv, Erinnerungen sind noch blockiert."
        case (false, true):
            return "Erinnerungen sind aktiv, Kalender ist noch blockiert."
        default:
            return "Aktiviere Kalender und Erinnerungen in der Datenschutz-Seite, damit Jarvis Termine und Erinnerungen sichtbar verwalten kann."
        }
    }

    private func permissionLabel(_ key: String) -> String {
        appState.permissions[key]?.allowed == true ? "Aktiv" : "Blockiert"
    }

    private func boolLabel(_ key: String) -> String {
        boolSetting(key) ? "Ja" : "Nein"
    }

    private func boolSetting(_ key: String) -> Bool {
        switch key {
        case "auto_calendar_from_mail_enabled":
            return true
        default:
            return false
        }
    }

    private func recentLine(containing terms: [String]) -> String {
        let match = appState.messages.reversed().first { message in
            let text = message.text.lowercased()
            return terms.contains { text.contains($0) }
        }
        return match?.text ?? "Noch keine Aktion"
    }

    private func firstCalendarTitle() -> String {
        appState.calendarOverview.calendar.items.first?.title ?? appState.calendarOverview.calendar.message
    }

    private func firstReminderTitle() -> String {
        appState.calendarOverview.reminders.items.first?.title ?? appState.calendarOverview.reminders.message
    }

    private func overviewRow(icon: String, title: String, detail: String, tint: Color) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 28, height: 28)
                .background(.thinMaterial, in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.callout.weight(.semibold))
                if !detail.isEmpty {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

struct RemindersWorkspaceView: View {
    @EnvironmentObject private var appState: AppState

    private var remindersAllowed: Bool {
        appState.permissions["reminders"]?.allowed ?? false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                permissionNotice
                statusCards
                quickActions
                resultPanel
            }
            .padding(28)
            .frame(maxWidth: 1040, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle("Erinnerungen")
        .task {
            await appState.refreshPermissions()
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            LiquidGlassIcon(symbol: "checklist", tint: .green)

            VStack(alignment: .leading, spacing: 6) {
                Text("Erinnerungen")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Text("Hier geht es um kleine Aufgaben mit Wirkung: Jarvis kann Erinnerungen anlegen, Status erklären und dir konkrete Vorlagen liefern.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(2)
            }
        }
        .liquidGlassPanel(tint: .green)
    }

    private var permissionNotice: some View {
        HStack(spacing: 12) {
            Image(systemName: remindersAllowed ? "checkmark.shield.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(remindersAllowed ? .green : .orange)
                .font(.title3)
            VStack(alignment: .leading, spacing: 3) {
                Text(remindersAllowed ? "Erinnerungen aktiv" : "Erinnerungen blockiert")
                    .font(.headline)
                Text(remindersAllowed ? "Jarvis darf Erinnerungen nach Bestätigung anlegen." : "Aktiviere Erinnerungen in der Datenschutz-Seite, damit Jarvis Aufgaben erstellen kann.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Datenschutz öffnen") {
                appState.selectedSection = .privacy
            }
            .buttonStyle(.borderedProminent)
        }
        .liquidGlassPanel(tint: remindersAllowed ? .green : .orange)
    }

    private var statusCards: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 14)], spacing: 14) {
            simpleCard(
                title: "Aktueller Status",
                subtitle: remindersAllowed ? "Zugriff erlaubt" : "Zugriff blockiert",
                symbol: remindersAllowed ? "checkmark.circle.fill" : "xmark.circle.fill",
                tint: remindersAllowed ? .green : .orange,
                details: [
                    ("Bereit", remindersAllowed ? "Ja" : "Nein"),
                    ("Letzte Aktion", recentLine(containing: ["erinner"])),
                    ("Hinweis", "Bestätigungen bleiben Pflicht")
                ]
            )
            simpleCard(
                title: "Typische Aufgabe",
                subtitle: "Ein guter Start ist eine Erinnerung für morgen oder für heute Abend.",
                symbol: "bell.badge.fill",
                tint: .green,
                details: [
                    ("Beispiel", "Erinnere mich morgen um 18 Uhr"),
                    ("Sprache", "Normale Umgangssprache"),
                    ("Verhalten", "Jarvis fragt bei Bedarf nach")
                ]
            )
        }
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("Schnellaktionen", subtitle: "Zum direkten Testen der Erinnerungsfunktion.")
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 14)], spacing: 14) {
                actionCard(
                    title: "Heute prüfen",
                    subtitle: "Fragt nach offenen Erinnerungen und Aufgaben für heute.",
                    symbol: "calendar.badge.clock",
                    command: "Jarvis, was steht heute an?"
                )
                actionCard(
                    title: "Neue Erinnerung",
                    subtitle: "Direktes Erstellen einer Erinnerung per Sprache.",
                    symbol: "bell.badge.fill",
                    command: "Jarvis, erstelle morgen um 18 Uhr eine Erinnerung, dass ich Codex weiter teste."
                )
                actionCard(
                    title: "Kurze Erinnerung",
                    subtitle: "Prüft, ob Jarvis den Titel sauber aus dem Satz zieht.",
                    symbol: "note.text.badge.plus",
                    command: "Jarvis, erstelle eine Erinnerung für meinen Einkaufszettel."
                )
            }
        }
    }

    private var resultPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Letztes Ergebnis", subtitle: "Die letzte Antwort aus dem Chat zu Erinnerungen.")
            Text(recentLine(containing: ["erinner", "termin"]))
                .font(.body)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .liquidGlassPanel(tint: .green)
    }

    private func actionCard(title: String, subtitle: String, symbol: String, command: String) -> some View {
        Button {
            Task { await appState.send(command) }
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol)
                        .font(.system(size: 21, weight: .semibold))
                        .foregroundStyle(.green)
                        .frame(width: 42, height: 42)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    Spacer()
                    Image(systemName: "arrow.right.circle")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 146, alignment: .topLeading)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
            )
            .shadow(color: Color.green.opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .buttonStyle(.plain)
    }

    private func simpleCard(title: String, subtitle: String, symbol: String, tint: Color, details: [(String, String)]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: symbol)
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 42, height: 42)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                Spacer()
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .foregroundStyle(.secondary)
                    .font(.callout)
            }

            VStack(alignment: .leading, spacing: 8) {
                ForEach(details.indices, id: \.self) { index in
                    let item = details[index]
                    HStack(alignment: .top, spacing: 10) {
                        Text(item.0)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .frame(width: 90, alignment: .leading)
                        Text(item.1)
                            .font(.callout)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                }
            }
            .padding(12)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 190, alignment: .topLeading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
        )
    }

    private func sectionHeader(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title2.weight(.bold))
            Text(subtitle)
                .foregroundStyle(.secondary)
        }
    }

    private func recentLine(containing terms: [String]) -> String {
        let match = appState.messages.reversed().first { message in
            let text = message.text.lowercased()
            return terms.contains { text.contains($0) }
        }
        return match?.text ?? "Noch keine Erinnerung angelegt"
    }
}
