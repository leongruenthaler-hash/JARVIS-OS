import EventKit
import Foundation

let isoFormatter = ISO8601DateFormatter()
var outputPath: String?

func emitData(_ data: Data) {
    if let outputPath = outputPath {
        try? data.write(to: URL(fileURLWithPath: outputPath))
        return
    }

    FileHandle.standardOutput.write(data)
}

func emit(_ message: String) {
    emitData(Data((message + "\n").utf8))
}

func fail(_ message: String) -> Never {
    emit("ERROR: \(message)")
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

struct EventRecord: Codable {
    let calendar: String
    let title: String
    let start: String
    let end: String
    let allDay: Bool
}

struct ReminderRecord: Codable {
    let list: String
    let title: String
    let due: String
}

let store = EKEventStore()

func statusName(_ status: EKAuthorizationStatus) -> String {
    switch status {
    case .fullAccess, .authorized:
        return "authorized"
    case .writeOnly:
        return "writeOnly"
    case .denied:
        return "denied"
    case .restricted:
        return "restricted"
    case .notDetermined:
        return "notDetermined"
    @unknown default:
        return "unknown"
    }
}

func statusAllowsRead(_ status: EKAuthorizationStatus) -> Bool {
    status == .fullAccess || status == .authorized
}

// requestFullAccessToEvents/Reminders (macOS 14+) sind die einzigen APIs, die
// tatsaechlich Lesezugriff erlauben - das Aeltere requestAccess(to:) liefert auf
// neueren macOS-Versionen nur noch writeOnly und wuerde events()/reminders()
// leer zurueckgeben, ohne dass das im Status sichtbar waere.
func authorize(entity: EKEntityType) -> Bool {
    let currentStatus = EKEventStore.authorizationStatus(for: entity)
    if statusAllowsRead(currentStatus) {
        return true
    }
    if currentStatus != .notDetermined {
        return false
    }

    var completed = false
    var granted = false
    let semaphore = DispatchSemaphore(value: 0)

    if entity == .event {
        store.requestFullAccessToEvents { ok, _ in
            granted = ok
            completed = true
            semaphore.signal()
        }
    } else {
        store.requestFullAccessToReminders { ok, _ in
            granted = ok
            completed = true
            semaphore.signal()
        }
    }

    _ = semaphore.wait(timeout: .now() + 60)
    return completed && granted
}

func formatDate(_ date: Date) -> String {
    isoFormatter.string(from: date)
}

// EKEventStore.predicateForEvents() verlangt eine begrenzte Zeitspanne (Apple-
// Dokumentation: max. 4 Jahre) - ohne explizites "until" (z.B. "naechste
// Termine" ohne Datumsgrenze) wird stattdessen 2 Jahre in die Zukunft
// abgefragt, danach client-seitig auf "limit" gekappt. Deutlich schneller als
// der bisherige AppleScript-Weg (der ALLE Termine aller Kalender einzeln per
// IPC abfragte - bei 349 Terminen allein fuer die Startdatum-Eigenschaft ueber
// 24s), weil EventKit die Termine nativ/indiziert durchsucht statt Property fuer
// Property per Skript-Bridge.
func listEvents(until: Date?, limit: Int) throws {
    guard authorize(entity: .event) else {
        fail("Kalender-Zugriff wurde nicht erlaubt. Status: \(statusName(EKEventStore.authorizationStatus(for: .event))).")
    }

    let start = Date()
    let end = until ?? start.addingTimeInterval(60 * 60 * 24 * 365 * 2)
    let calendars = store.calendars(for: .event)
    let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
    let events = store.events(matching: predicate)
        .filter { $0.startDate > start }
        .sorted { $0.startDate < $1.startDate }
        .prefix(limit)

    let records = events.map { event in
        EventRecord(
            calendar: event.calendar?.title ?? "",
            title: event.title ?? "",
            start: formatDate(event.startDate),
            end: formatDate(event.endDate),
            allDay: event.isAllDay
        )
    }

    let data = try JSONEncoder().encode(Array(records))
    emitData(data)
}

func listReminders(limit: Int) throws {
    guard authorize(entity: .reminder) else {
        fail("Erinnerungen-Zugriff wurde nicht erlaubt. Status: \(statusName(EKEventStore.authorizationStatus(for: .reminder))).")
    }

    let calendars = store.calendars(for: .reminder)
    let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: calendars)

    var fetched: [EKReminder] = []
    let semaphore = DispatchSemaphore(value: 0)
    store.fetchReminders(matching: predicate) { reminders in
        fetched = reminders ?? []
        semaphore.signal()
    }
    _ = semaphore.wait(timeout: .now() + 30)

    let sorted = fetched.sorted { lhs, rhs in
        let lhsDate = lhs.dueDateComponents?.date ?? Date.distantFuture
        let rhsDate = rhs.dueDateComponents?.date ?? Date.distantFuture
        return lhsDate < rhsDate
    }
    let limited = sorted.prefix(limit)

    let records = limited.map { reminder in
        ReminderRecord(
            list: reminder.calendar?.title ?? "",
            title: reminder.title ?? "",
            due: reminder.dueDateComponents?.date.map(formatDate) ?? ""
        )
    }

    let data = try JSONEncoder().encode(Array(records))
    emitData(data)
}

var args = CommandLine.arguments
if let outputIndex = args.firstIndex(of: "--output"), outputIndex + 1 < args.count {
    outputPath = args[outputIndex + 1]
    args.removeSubrange(outputIndex...outputIndex + 1)
}
var untilArg: String?
if let untilIndex = args.firstIndex(of: "--until"), untilIndex + 1 < args.count {
    untilArg = args[untilIndex + 1]
    args.removeSubrange(untilIndex...untilIndex + 1)
}
var limitArg = 5
if let limitIndex = args.firstIndex(of: "--limit"), limitIndex + 1 < args.count {
    limitArg = Int(args[limitIndex + 1]) ?? 5
    args.removeSubrange(limitIndex...limitIndex + 1)
}

guard args.count >= 2 else {
    fail("Befehl fehlt: status, events oder reminders.")
}

if args[1] == "status" {
    emit("events:\(statusName(EKEventStore.authorizationStatus(for: .event)))")
    emit("reminders:\(statusName(EKEventStore.authorizationStatus(for: .reminder)))")
    exit(0)
}

do {
    switch args[1] {
    case "events":
        var untilDate: Date?
        if let untilArg = untilArg {
            untilDate = isoFormatter.date(from: untilArg)
        }
        try listEvents(until: untilDate, limit: limitArg)
    case "reminders":
        try listReminders(limit: limitArg)
    default:
        fail("Unbekannter Befehl: \(args[1])")
    }
} catch {
    fail("Kalender-Fehler: \(error.localizedDescription)")
}
