import Foundation
import SwiftUI

let jarvisAppVersion = "Beta 0.1"

enum JarvisSection: String, CaseIterable, Identifiable {
    case home = "Home"
    case actions = "Aktionszentrale"
    case chat = "Chat"
    case calendar = "Kalender"
    case mail = "Mail"
    case reminders = "Erinnerungen"
    case files = "Dateien"
    case photos = "Fotos"
    case memory = "Gedächtnis"
    case automations = "Automationen"
    case privacy = "Datenschutz"
    case licenses = "Lizenzen"
    case settings = "Einstellungen"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .home: "house.fill"
        case .actions: "rectangle.grid.2x2.fill"
        case .chat: "bubble.left.and.bubble.right"
        case .calendar: "calendar"
        case .mail: "envelope"
        case .reminders: "checklist"
        case .files: "folder"
        case .photos: "photo.on.rectangle"
        case .memory: "brain.head.profile"
        case .automations: "bolt.badge.clock"
        case .privacy: "hand.raised"
        case .licenses: "doc.text.magnifyingglass"
        case .settings: "gearshape"
        }
    }
}

enum JarvisRuntimeStatus: String {
    case idle = "Verbunden"
    case listening = "Zuhören"
    case transcribing = "Transkribieren"
    case thinking = "Denkt nach"
    case responding = "Antwortet"
    case offline = "Nicht verbunden"
}

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: Role
    var text: String
    let date = Date()

    enum Role: Equatable {
        case user
        case jarvis
        case system
    }
}

struct ServerHealth: Codable {
    let ok: Bool
    let provider: String
    let activeModel: String
    let openAIEnabled: Bool
    let ollamaInstalled: Bool
    let ollamaRunning: Bool

    enum CodingKeys: String, CodingKey {
        case ok, provider
        case activeModel = "active_model"
        case openAIEnabled = "openai_enabled"
        case ollamaInstalled = "ollama_installed"
        case ollamaRunning = "ollama_running"
    }
}

/// A Calendar event / Reminder the backend detected in a mail (invoice due date, meeting
/// invite, deadline, ...) but has NOT created yet - inbound mail is untrusted content, so
/// these always need an explicit confirm/dismiss via `resolveCalendarAction` before
/// anything is written to Calendar.app. See mail_calendar_actions.py.
struct PendingCalendarAction: Codable, Identifiable, Equatable {
    var id: String { actionKey }
    let actionKey: String
    let kind: String
    let title: String
    let when: String
    let source: String

    enum CodingKeys: String, CodingKey {
        case actionKey = "action_key"
        case kind
        case title
        case when
        case source
    }
}

struct PendingCalendarActionsResponse: Codable {
    let actions: [PendingCalendarAction]
}

/// A stored long-term fact (Phase B / Context Engine, see app/memory.py). Fields beyond
/// content/category existed nowhere before Phase B - every fact now carries provenance
/// (source_type), a sensitivity level, and an optional expiry, so the Memory view can
/// show and let the user correct all of it instead of a flat, opaque fact list.
struct MemoryFact: Codable, Identifiable, Equatable {
    let id: String
    var content: String
    var category: String
    var scope: String
    var sourceType: String
    var sensitivity: String
    var confidence: Double
    var retentionPolicy: String
    var expiresAt: String?
    var userConfirmed: Bool
    var status: String
    var tags: [String]
    let createdAt: String
    let updatedAt: String
    let lastUsedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, content, category, scope, sensitivity, confidence, status, tags
        case sourceType = "source_type"
        case retentionPolicy = "retention_policy"
        case expiresAt = "expires_at"
        case userConfirmed = "user_confirmed"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case lastUsedAt = "last_used_at"
    }
}

struct MemoryFactsResponse: Codable {
    let facts: [MemoryFact]
    let total: Int
}

/// A single "Jarvis just touched this" event (Phase F-Folgeschritt, see
/// app/core/activity_log.py) - fired when a specific photo/file gets exported or
/// copied, or a memory fact actually gets used in a prompt. Feeds the live-access
/// flare animation in MemoryCoreView, not a persisted record - purely transient.
struct ActivityEvent: Codable, Identifiable, Equatable {
    var type: String
    var label: String
    var reference: String?
    var at: TimeInterval

    var id: String { "\(type)-\(at)-\(label)" }

    enum CodingKeys: String, CodingKey {
        case type, label, reference, at
    }
}

struct ActivityEventsResponse: Codable {
    let events: [ActivityEvent]
}

/// "Automationen"-Ansicht (2026-09-12, ersetzt die zuvor migrierte, nie
/// wirklich genutzte interne Aufgabenliste): zeigt die echten OpenClaw-
/// Cronjobs (mail-summary-watch, calendar-30min-reminder, proaktive
/// Watch-Automationen etc.) - siehe scripts/automations_proxy_server.py.
/// Rein lesend, Steuerung bleibt Sache von `openclaw cron edit/run`.
struct AutomationJob: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let description: String
    let enabled: Bool
    let schedule: String
    let status: String
    let lastRunAtMs: Double?
    let nextRunAtMs: Double?
    let lastError: String?

    enum CodingKeys: String, CodingKey {
        case id, name, description, enabled, schedule, status
        case lastRunAtMs = "last_run_at_ms"
        case nextRunAtMs = "next_run_at_ms"
        case lastError = "last_error"
    }
}

struct AutomationsResponse: Codable {
    let automations: [AutomationJob]
    let total: Int
}

struct FileSearchPayload: Codable, Equatable {
    let query: String
    let message: String
    let results: [FileSearchResult]
}

struct FileSearchResult: Codable, Identifiable, Equatable {
    let name: String
    let kind: String
    let root: String
    let relativePath: String
    let path: String
    let modified: String
    let size: Int
    let fileExtension: String

    var id: String {
        if !path.isEmpty { return path }
        return [root, relativePath, name].joined(separator: "/")
    }

    var isFolder: Bool {
        kind == "folder"
    }

    var kindLabel: String {
        isFolder ? "Ordner" : "Datei"
    }

    var rootLabel: String {
        switch root.lowercased() {
        case "desktop", "schreibtisch": return "Schreibtisch"
        case "documents", "dokumente": return "Dokumente"
        case "downloads", "download": return "Downloads"
        case "jarvis", "projekt": return "Jarvis"
        default: return root.isEmpty ? "Lokaler Index" : root
        }
    }

    var locationLabel: String {
        let parent = URL(fileURLWithPath: relativePath).deletingLastPathComponent().path
        if parent.isEmpty || parent == "." || parent == "/" {
            return rootLabel
        }
        return "\(rootLabel)/\(parent.trimmingCharacters(in: CharacterSet(charactersIn: "/")))"
    }

    enum CodingKeys: String, CodingKey {
        case name
        case kind
        case root
        case relativePath = "relative_path"
        case path
        case modified
        case size
        case fileExtension = "extension"
    }
}
